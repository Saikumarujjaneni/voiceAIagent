"""
Generate architecture diagram as PNG using only Python stdlib (no dependencies).
Produces: docs/architecture.png
Run: python docs/generate_diagram.py
"""
import struct
import zlib
import os

# ── Canvas settings ──────────────────────────────────────────────────────────
W, H = 1100, 820
BG       = (15,  22,  35)   # dark navy
C_BLUE   = (45, 108, 223)   # accent blue
C_GREEN  = (26,  77,  54)   # memory green
C_PURPLE = (72,  52, 120)   # scheduling purple
C_ORANGE = (140,  80,  20)  # campaign orange
C_DARK   = (21,  29,  40)   # panel dark
C_BORDER = (42,  56,  72)   # border grey
C_WHITE  = (232, 238, 245)
C_LBLUE  = (168, 212, 255)
C_LGREEN = (184, 245, 200)
C_LYELLOW= (255, 233, 168)
C_LPURP  = (200, 180, 255)

# ── Pixel buffer ─────────────────────────────────────────────────────────────
pixels = [list(BG) for _ in range(W * H)]

def idx(x, y):
    return y * W + x

def set_px(x, y, color):
    if 0 <= x < W and 0 <= y < H:
        pixels[idx(x, y)] = list(color)

def blend(base, over, alpha):
    return tuple(int(base[i] * (1 - alpha) + over[i] * alpha) for i in range(3))

def fill_rect(x, y, w, h, color):
    for row in range(y, y + h):
        for col in range(x, x + w):
            set_px(col, row, color)

def draw_rect_border(x, y, w, h, color, thickness=2):
    for t in range(thickness):
        for col in range(x + t, x + w - t):
            set_px(col, y + t, color)
            set_px(col, y + h - 1 - t, color)
        for row in range(y + t, y + h - t):
            set_px(x + t, row, color)
            set_px(x + w - 1 - t, row, color)

def rounded_rect(x, y, w, h, fill, border, radius=8, bthick=2):
    fill_rect(x + radius, y, w - 2*radius, h, fill)
    fill_rect(x, y + radius, w, h - 2*radius, fill)
    for dy in range(radius):
        for dx in range(radius):
            dist = ((dx - radius)**2 + (dy - radius)**2) ** 0.5
            if dist <= radius:
                set_px(x + dx, y + dy, fill)
                set_px(x + w - 1 - dx, y + dy, fill)
                set_px(x + dx, y + h - 1 - dy, fill)
                set_px(x + w - 1 - dx, y + h - 1 - dy, fill)
    draw_rect_border(x, y, w, h, border, bthick)

def draw_arrow_v(x, y1, y2, color, thickness=2):
    for t in range(thickness):
        for row in range(min(y1,y2), max(y1,y2)):
            set_px(x + t, row, color)
    # arrowhead
    for i in range(6):
        for j in range(-i, i+1):
            set_px(x + thickness//2 + j, max(y1,y2) + i, color)

def draw_arrow_h(x1, x2, y, color, thickness=2):
    for t in range(thickness):
        for col in range(min(x1,x2), max(x1,x2)):
            set_px(col, y + t, color)
    tip_x = max(x1, x2)
    for i in range(6):
        for j in range(-i, i+1):
            set_px(tip_x + i, y + thickness//2 + j, color)


# ── 5×7 bitmap font (printable ASCII 32-126) ─────────────────────────────────
FONT = {
 ' ':0x0000000,'!':0x2104210,'\"':0x0A50000,
 '#':0x0AFABEA,'$':0x23E8FA2,'%':0x4C94B22,
 '&':0x45A4A4A,'\'':0x2104000,'(':0x1084421,')':0x4421108,
 '*':0x0A8C8A0,'+':0x020FA20,',':0x0000C84,'-':0x000F800,
 '.':0x0000C00,'/':0x0842108,'0':0x74A5297,'1':0x6104214,
 '2':0x74041F0,'3':0x7404297,'4':0x14ABEF0,'5':0x7C3C297,
 '6':0x74BC297,'7':0x7C10842,'8':0x74BC297,'9':0x74BE097,
 ':':0x00C0C00,';':0x00C0C84,'<':0x0842108,'>':0x2108420,
 '=':0x00F80F8,'?':0x7404210,'@':0x74BBEF0,
 'A':0x74BBEF0,'B':0x74BBEF7,'C':0x74842F0,'D':0x74A52F7,
 'E':0x7C3C3F0,'F':0x7C3C200,'G':0x74BC2F0,'H':0x52BBEF0,
 'I':0x7104217,'J':0x7104297,'K':0x52CA4A0,'L':0x4210BF0,
 'M':0x5ABBEF0,'N':0x52B5EF0,'O':0x74A52F0,'P':0x74BBEC0,
 'Q':0x74A52F2,'R':0x74BBEC8,'S':0x74BC297,'T':0x7104210,
 'U':0x52A52F0,'V':0x52A5140,'W':0x52ABAA0,'X':0x52888A0,
 'Y':0x52888C0,'Z':0x7C10BF0,
 'a':0x00E0BE0,'b':0x42EBBF0,'c':0x00E842F,'d':0x10EBBF0,
 'e':0x00E8BE0,'f':0x30842F0,'g':0x00EBBE0,'h':0x42EBBF0,
 'i':0x2004210,'j':0x2004297,'k':0x42CA4A0,'l':0x6104210,
 'm':0x00ABBF0,'n':0x00ABBF0,'o':0x00E8BE0,'p':0x00EBBE0,
 'q':0x00EBBE0,'r':0x00E8420,'s':0x00E8BE0,'t':0x42F4210,
 'u':0x00A52F0,'v':0x00A5140,'w':0x00ABAA0,'x':0x00888A0,
 'y':0x00A52F0,'z':0x00F0BE0,
}

def draw_char(cx, cy, ch, color, scale=1):
    bits = FONT.get(ch.upper() if ch.upper() in FONT else ch, FONT.get(ch, 0))
    for row in range(7):
        for col in range(5):
            bit_pos = (6 - row) * 5 + (4 - col)
            if (bits >> bit_pos) & 1:
                for sy in range(scale):
                    for sx in range(scale):
                        set_px(cx + col*scale + sx, cy + row*scale + sy, color)

def draw_text(x, y, text, color, scale=1):
    cx = x
    for ch in text:
        draw_char(cx, y, ch, color, scale)
        cx += (5 + 1) * scale

def text_width(text, scale=1):
    return len(text) * (5 + 1) * scale

def draw_text_centered(cx, y, text, color, scale=1):
    w = text_width(text, scale)
    draw_text(cx - w // 2, y, text, color, scale)


# ── Layout constants ──────────────────────────────────────────────────────────
PAD = 30

# Column x-centers
COL1 = 130   # Client / STT
COL2 = 370   # Voice Gateway
COL3 = 610   # Agent
COL4 = 850   # Memory / Tools / Scheduling

BOX_W = 200
BOX_H = 52

def box(cx, cy, label, sublabel, fill, border, lcolor=C_WHITE, scale=1):
    x = cx - BOX_W // 2
    y = cy - BOX_H // 2
    rounded_rect(x, y, BOX_W, BOX_H, fill, border, radius=8, bthick=2)
    draw_text_centered(cx, cy - 10, label, lcolor, scale)
    if sublabel:
        draw_text_centered(cx, cy + 6, sublabel, C_LBLUE, 1)

# ── Title ─────────────────────────────────────────────────────────────────────
fill_rect(0, 0, W, 56, (20, 30, 48))
draw_rect_border(0, 0, W, 56, C_BLUE, 2)
draw_text_centered(W//2, 10, "CLINICAL VOICE AGENT", C_WHITE, 2)
draw_text_centered(W//2, 34, "REAL-TIME MULTILINGUAL ARCHITECTURE", C_LBLUE, 1)

# ── Section labels ────────────────────────────────────────────────────────────
def section_label(x, y, text, color):
    tw = text_width(text, 1)
    fill_rect(x - 4, y - 2, tw + 8, 12, BG)
    draw_text(x, y, text, color, 1)

# ── Draw pipeline boxes ───────────────────────────────────────────────────────

# Row Y positions
R1 = 110   # Microphone / User
R2 = 185   # STT
R3 = 260   # Language Detection
R4 = 335   # Voice Gateway WS
R5 = 410   # AI Agent (LLM)
R6 = 485   # Tool Orchestrator
R7 = 560   # Scheduling Service
R8 = 635   # Memory (Session)
R9 = 710   # Memory (Persistent)

# ── Left column: Client ───────────────────────────────────────────────────────
section_label(PAD, 72, "CLIENT  (BROWSER)", C_LBLUE)
rounded_rect(PAD, 80, 220, 200, (18, 26, 40), C_BLUE, 8, 2)

box(PAD + 110, R1,      "MICROPHONE",    "User Speech",       (30, 50, 90),  C_BLUE)
box(PAD + 110, R2,      "STT",           "Web Speech API",    C_BLUE,        C_BLUE, C_WHITE, 1)
box(PAD + 110, R3,      "LANG DETECT",   "langdetect lib",    (40, 60, 100), C_BLUE)

# arrows inside client column
draw_arrow_v(PAD + 110, R1 + BOX_H//2, R2 - BOX_H//2, C_LBLUE)
draw_arrow_v(PAD + 110, R2 + BOX_H//2, R3 - BOX_H//2, C_LBLUE)

# ── Middle-left: Voice Gateway ────────────────────────────────────────────────
GW_X = 280
section_label(GW_X, 72, "VOICE GATEWAY  (TYPESCRIPT)", C_LGREEN)
rounded_rect(GW_X, 80, 220, 200, (18, 30, 26), C_GREEN, 8, 2)

box(GW_X + 110, R1, "WEBSOCKET",    "ws server :3000",   (26, 60, 46),  C_GREEN)
box(GW_X + 110, R2, "BARGE-IN",     "interrupt handler", (26, 60, 46),  C_GREEN)
box(GW_X + 110, R3, "LATENCY",      "e2e measurement",   (26, 60, 46),  C_GREEN)

draw_arrow_v(GW_X + 110, R1 + BOX_H//2, R2 - BOX_H//2, C_LGREEN)
draw_arrow_v(GW_X + 110, R2 + BOX_H//2, R3 - BOX_H//2, C_LGREEN)

# ── Middle-right: Backend Agent ───────────────────────────────────────────────
AG_X = 530
section_label(AG_X, 72, "BACKEND  (PYTHON / FASTAPI)", C_LYELLOW)
rounded_rect(AG_X, 80, 220, 340, (30, 26, 18), C_ORANGE, 8, 2)

box(AG_X + 110, R1, "FASTAPI",      "/api/v1",           (60, 46, 20),  C_ORANGE)
box(AG_X + 110, R2, "ORCHESTRATOR", "agent loop x6",     C_ORANGE,      C_ORANGE, C_WHITE, 1)
box(AG_X + 110, R3, "LLM",          "gpt-4o-mini",       (60, 46, 20),  C_ORANGE)
box(AG_X + 110, R4, "TOOL EXEC",    "8 tools",           (60, 46, 20),  C_ORANGE)
box(AG_X + 110, R5, "CAMPAIGNS",    "outbound queue",    (60, 46, 20),  C_ORANGE)

draw_arrow_v(AG_X + 110, R1 + BOX_H//2, R2 - BOX_H//2, C_LYELLOW)
draw_arrow_v(AG_X + 110, R2 + BOX_H//2, R3 - BOX_H//2, C_LYELLOW)
draw_arrow_v(AG_X + 110, R3 + BOX_H//2, R4 - BOX_H//2, C_LYELLOW)
draw_arrow_v(AG_X + 110, R4 + BOX_H//2, R5 - BOX_H//2, C_LYELLOW)

# ── Right column: Data / Memory / Scheduling ──────────────────────────────────
DB_X = 790
section_label(DB_X, 72, "DATA  LAYER", C_LPURP)
rounded_rect(DB_X, 80, 220, 340, (26, 18, 40), C_PURPLE, 8, 2)

box(DB_X + 110, R1, "SESSION MEM",  "Redis TTL 1h",      C_PURPLE,      C_PURPLE, C_WHITE, 1)
box(DB_X + 110, R2, "PATIENT MEM",  "Redis TTL 90d",     (60, 40, 100), C_PURPLE)
box(DB_X + 110, R3, "SQLITE DB",    "appointments",      (60, 40, 100), C_PURPLE)
box(DB_X + 110, R4, "SCHEDULING",   "conflict detect",   (80, 40, 120), C_PURPLE)
box(DB_X + 110, R5, "INTERACTION",  "history logs",      (60, 40, 100), C_PURPLE)

draw_arrow_v(DB_X + 110, R1 + BOX_H//2, R2 - BOX_H//2, C_LPURP)
draw_arrow_v(DB_X + 110, R2 + BOX_H//2, R3 - BOX_H//2, C_LPURP)
draw_arrow_v(DB_X + 110, R3 + BOX_H//2, R4 - BOX_H//2, C_LPURP)
draw_arrow_v(DB_X + 110, R4 + BOX_H//2, R5 - BOX_H//2, C_LPURP)

# ── Cross-column arrows ───────────────────────────────────────────────────────
# Client STT → Gateway WS
draw_arrow_h(PAD + 220, GW_X, R2, C_LBLUE)
# Gateway → Backend
draw_arrow_h(GW_X + 220, AG_X, R2, C_LGREEN)
# Backend Tool Exec → Data Layer
draw_arrow_h(AG_X + 220, DB_X, R4, C_LYELLOW)
# Backend Orchestrator ↔ Session Memory
draw_arrow_h(AG_X + 220, DB_X, R1, C_LYELLOW)


# ── Latency pipeline strip at bottom ─────────────────────────────────────────
STRIP_Y = 460
fill_rect(PAD, STRIP_Y, W - 2*PAD, 70, (18, 24, 36))
draw_rect_border(PAD, STRIP_Y, W - 2*PAD, 70, C_BORDER, 1)
draw_text_centered(W//2, STRIP_Y + 6, "LATENCY PIPELINE  (TARGET < 450 MS)", C_LYELLOW, 1)

stages = [
    ("SPEECH END", "0 ms"),
    ("STT DONE", "~120 ms"),
    ("AGENT START", "~130 ms"),
    ("AGENT DONE", "~330 ms"),
    ("TTS FIRST BYTE", "~430 ms"),
]
seg_w = (W - 2*PAD) // len(stages)
for i, (label, timing) in enumerate(stages):
    sx = PAD + i * seg_w + seg_w // 2
    sy = STRIP_Y + 22
    fill_rect(sx - 4, sy - 4, 8, 8, C_BLUE)
    draw_text_centered(sx, sy + 8, label, C_WHITE, 1)
    draw_text_centered(sx, sy + 20, timing, C_LBLUE, 1)
    if i < len(stages) - 1:
        draw_arrow_h(sx + 4, sx + seg_w - 4, sy, C_BORDER)

# ── Legend ────────────────────────────────────────────────────────────────────
LEG_Y = 548
fill_rect(PAD, LEG_Y, W - 2*PAD, 56, (18, 24, 36))
draw_rect_border(PAD, LEG_Y, W - 2*PAD, 56, C_BORDER, 1)
draw_text(PAD + 10, LEG_Y + 6, "LEGEND:", C_WHITE, 1)

legend_items = [
    (C_BLUE,   "STT / Voice Gateway"),
    (C_GREEN,  "WebSocket / Barge-in"),
    (C_ORANGE, "AI Agent / LLM / Tools"),
    (C_PURPLE, "Memory / Scheduling / DB"),
]
lx = PAD + 10
for color, label in legend_items:
    fill_rect(lx, LEG_Y + 22, 14, 14, color)
    draw_rect_border(lx, LEG_Y + 22, 14, 14, C_BORDER, 1)
    draw_text(lx + 18, LEG_Y + 25, label, C_WHITE, 1)
    lx += text_width(label, 1) + 40

# ── Tool list box ─────────────────────────────────────────────────────────────
TOOL_Y = 620
fill_rect(PAD, TOOL_Y, W - 2*PAD, 80, (18, 24, 36))
draw_rect_border(PAD, TOOL_Y, W - 2*PAD, 80, C_BORDER, 1)
draw_text(PAD + 10, TOOL_Y + 6, "TOOLS:", C_LYELLOW, 1)

tools_row1 = ["list_doctors", "get_availability", "book_appointment", "cancel_appointment"]
tools_row2 = ["reschedule_appointment", "list_my_appointments", "log_campaign_outcome", "update_session_intent"]
tx = PAD + 10
for t in tools_row1:
    rounded_rect(tx, TOOL_Y + 20, text_width(t, 1) + 10, 16, (40, 30, 70), C_PURPLE, 4, 1)
    draw_text(tx + 5, TOOL_Y + 24, t, C_LPURP, 1)
    tx += text_width(t, 1) + 18
tx = PAD + 10
for t in tools_row2:
    rounded_rect(tx, TOOL_Y + 42, text_width(t, 1) + 10, 16, (40, 30, 70), C_PURPLE, 4, 1)
    draw_text(tx + 5, TOOL_Y + 46, t, C_LPURP, 1)
    tx += text_width(t, 1) + 18

# ── Footer ────────────────────────────────────────────────────────────────────
fill_rect(0, H - 24, W, 24, (12, 18, 28))
draw_text_centered(W//2, H - 18, "2Care.ai Assignment  |  EN / HI / TA  |  WebSocket + FastAPI + OpenAI + Redis + SQLite", C_BORDER, 1)

# ── Write PNG ─────────────────────────────────────────────────────────────────
def write_png(path, pixels, width, height):
    def png_chunk(tag, data):
        c = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', c)

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type None
        for x in range(width):
            r, g, b = pixels[y * width + x]
            raw.extend([r, g, b])

    compressed = zlib.compress(bytes(raw), 9)
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    png = b'\x89PNG\r\n\x1a\n'
    png += png_chunk(b'IHDR', ihdr)
    png += png_chunk(b'IDAT', compressed)
    png += png_chunk(b'IEND', b'')
    with open(path, 'wb') as f:
        f.write(png)

out_path = os.path.join(os.path.dirname(__file__), "architecture.png")
write_png(out_path, pixels, W, H)
print(f"Saved: {out_path}  ({W}x{H}px)")
