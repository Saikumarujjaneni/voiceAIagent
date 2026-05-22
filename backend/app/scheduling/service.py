from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.scheduling.models import Appointment, AppointmentStatus, Doctor, Patient


SLOT_MINUTES = 30
CLINIC_OPEN_HOUR = 9
CLINIC_CLOSE_HOUR = 18


class SchedulingError(Exception):
    def __init__(self, code: str, message: str, alternatives: list[dict[str, Any]] | None = None):
        self.code = code
        self.message = message
        self.alternatives = alternatives or []
        super().__init__(message)


async def seed_if_empty(db: AsyncSession) -> None:
    doctors = (await db.execute(select(Doctor))).scalars().all()
    if doctors:
        return
    for name, specialty in [
        ("Dr. Priya Sharma", "General Medicine"),
        ("Dr. Arun Kumar", "Cardiology"),
        ("Dr. Meena Rajan", "Pediatrics"),
    ]:
        db.add(Doctor(name=name, specialty=specialty))
    await db.commit()


def _parse_iso(dt: str) -> datetime:
    parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _slot_end(start: datetime) -> datetime:
    return start + timedelta(minutes=SLOT_MINUTES)


def _within_clinic_hours(start: datetime) -> bool:
    return CLINIC_OPEN_HOUR <= start.hour < CLINIC_CLOSE_HOUR and start.weekday() < 6


async def list_doctors(db: AsyncSession, specialty: str | None = None) -> list[dict[str, Any]]:
    q = select(Doctor)
    if specialty:
        q = q.where(Doctor.specialty.ilike(f"%{specialty}%"))
    rows = (await db.execute(q)).scalars().all()
    return [{"id": d.id, "name": d.name, "specialty": d.specialty} for d in rows]


async def get_availability(
    db: AsyncSession,
    doctor_id: int,
    day: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    day_start = _parse_iso(f"{day}T00:00:00+00:00").replace(hour=CLINIC_OPEN_HOUR, minute=0)
    slots: list[dict[str, Any]] = []
    cursor = day_start
    day_end = day_start.replace(hour=CLINIC_CLOSE_HOUR)

    booked = (
        await db.execute(
            select(Appointment.starts_at).where(
                and_(
                    Appointment.doctor_id == doctor_id,
                    Appointment.status == AppointmentStatus.CONFIRMED.value,
                    Appointment.starts_at >= day_start,
                    Appointment.starts_at < day_end,
                )
            )
        )
    ).scalars().all()
    booked_set = {b.replace(second=0, microsecond=0) for b in booked}

    while cursor < day_end and len(slots) < limit:
        if _within_clinic_hours(cursor) and cursor > datetime.now(UTC) and cursor not in booked_set:
            slots.append(
                {
                    "starts_at": cursor.isoformat(),
                    "ends_at": _slot_end(cursor).isoformat(),
                    "doctor_id": doctor_id,
                }
            )
        cursor += timedelta(minutes=SLOT_MINUTES)
    return slots


async def _find_alternatives(
    db: AsyncSession,
    doctor_id: int,
    desired: datetime,
    count: int = 3,
) -> list[dict[str, Any]]:
    alts: list[dict[str, Any]] = []
    for offset_days in range(0, 7):
        day = (desired + timedelta(days=offset_days)).date().isoformat()
        for slot in await get_availability(db, doctor_id, day, limit=count):
            if slot["starts_at"] != desired.isoformat():
                alts.append(slot)
            if len(alts) >= count:
                return alts
    return alts


async def book_appointment(
    db: AsyncSession,
    patient_id: str,
    doctor_id: int,
    starts_at: str,
) -> dict[str, Any]:
    start = _parse_iso(starts_at)
    if start <= datetime.now(UTC):
        raise SchedulingError("past_time", "Cannot book a slot in the past.")
    if not _within_clinic_hours(start):
        raise SchedulingError("outside_hours", "Clinic is closed at that time.")

    doctor = await db.get(Doctor, doctor_id)
    if not doctor:
        raise SchedulingError("doctor_unavailable", "Doctor not found.")

    conflict = (
        await db.execute(
            select(Appointment).where(
                and_(
                    Appointment.doctor_id == doctor_id,
                    Appointment.starts_at == start.replace(second=0, microsecond=0),
                    Appointment.status == AppointmentStatus.CONFIRMED.value,
                )
            )
        )
    ).scalar_one_or_none()
    if conflict:
        alts = await _find_alternatives(db, doctor_id, start)
        raise SchedulingError(
            "double_booking",
            "That slot is already taken.",
            alternatives=alts,
        )

    appt = Appointment(
        patient_id=patient_id,
        doctor_id=doctor_id,
        starts_at=start.replace(second=0, microsecond=0),
        ends_at=_slot_end(start),
        status=AppointmentStatus.CONFIRMED.value,
    )
    db.add(appt)
    await db.commit()
    await db.refresh(appt)
    return {
        "appointment_id": appt.id,
        "doctor": doctor.name,
        "starts_at": appt.starts_at.isoformat(),
        "status": appt.status,
    }


async def cancel_appointment(db: AsyncSession, patient_id: str, appointment_id: int) -> dict[str, Any]:
    appt = await db.get(Appointment, appointment_id)
    if not appt or appt.patient_id != patient_id:
        raise SchedulingError("not_found", "Appointment not found for this patient.")
    appt.status = AppointmentStatus.CANCELLED.value
    await db.commit()
    return {"appointment_id": appointment_id, "status": appt.status}


async def reschedule_appointment(
    db: AsyncSession,
    patient_id: str,
    appointment_id: int,
    new_starts_at: str,
) -> dict[str, Any]:
    appt = await db.get(Appointment, appointment_id)
    if not appt or appt.patient_id != patient_id:
        raise SchedulingError("not_found", "Appointment not found for this patient.")
    appt.status = AppointmentStatus.RESCHEDULED.value
    await db.commit()
    return await book_appointment(db, patient_id, appt.doctor_id, new_starts_at)


async def list_patient_appointments(db: AsyncSession, patient_id: str) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(Appointment, Doctor)
            .join(Doctor)
            .where(
                and_(
                    Appointment.patient_id == patient_id,
                    Appointment.status == AppointmentStatus.CONFIRMED.value,
                    Appointment.starts_at >= datetime.now(UTC),
                )
            )
            .order_by(Appointment.starts_at)
        )
    ).all()
    return [
        {
            "appointment_id": a.id,
            "doctor": d.name,
            "specialty": d.specialty,
            "starts_at": a.starts_at.isoformat(),
        }
        for a, d in rows
    ]


async def ensure_patient(
    db: AsyncSession,
    patient_id: str,
    name: str,
    phone: str,
    preferred_language: str = "en",
) -> Patient:
    patient = await db.get(Patient, patient_id)
    if patient:
        if preferred_language and patient.preferred_language != preferred_language:
            patient.preferred_language = preferred_language
            await db.commit()
        return patient
    patient = Patient(
        id=patient_id,
        name=name,
        phone=phone,
        preferred_language=preferred_language,
    )
    db.add(patient)
    await db.commit()
    return patient
