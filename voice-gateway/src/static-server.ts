import express from "express";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = Number(process.env.CLIENT_PORT ?? 3000);

app.use(express.static(path.join(__dirname, "../public")));

app.listen(PORT, () => {
  console.log(`Demo UI http://127.0.0.1:${PORT}`);
});
