// web/lib/utils.ts

export function formatNumberIndo(num: number): string {
  if (isNaN(num)) return "0";
  return new Intl.NumberFormat("id-ID").format(num);
}

const ACRONYMS = new Set([
  "RI", "KKP", "CPO", "B40", "B35", "EUDR", "DSI", "PTPN", "KPK", "MUI",
  "FGD", "PMI", "IKI", "DBHCHT", "IKMA", "IKFT", "IA", "APEC", "G20",
  "AS", "USA", "WIB", "WITA", "WIT", "PPKS", "PT", "CV", "DPR", "DPRD",
  "KEMENPERIN", "KEMENDAG", "BPDPKS", "RSPO", "ISPO", "F&B", "NPPBKC", "CVC"
]);

export function normalizeTitle(title: string): string {
  if (!title) return "";
  const trimmed = title.trim();
  
  // Cek apakah seluruh huruf adalah kapital (all-caps)
  const lettersOnly = trimmed.replace(/[^a-zA-Z]/g, "");
  const isAllCaps = lettersOnly.length > 5 && lettersOnly === lettersOnly.toUpperCase();
  
  if (!isAllCaps) {
    return trimmed;
  }

  // Jika all-caps, ubah ke title case dengan mempertahankan akronim penting
  return trimmed
    .split(/\s+/)
    .map((word, idx) => {
      // Ambil karakter tanpa tanda baca
      const cleanWord = word.replace(/[^a-zA-Z0-9]/g, "").toUpperCase();
      if (ACRONYMS.has(cleanWord)) {
        return word.toUpperCase();
      }
      
      const lower = word.toLowerCase();
      // Kata hubung kecil jika bukan kata pertama
      if (idx > 0 && ["dan", "atau", "di", "ke", "dari", "yang", "untuk", "pada", "tentang", "jadi"].includes(lower)) {
        return lower;
      }
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(" ")
    .replace(/\s+:\s+/g, ": ");
}

export function normalizeMedia(media: string): string {
  if (!media) return "Media Nasional";
  let m = media.trim();

  // Khusus media umum yang menyatu
  if (m.toLowerCase() === "detikcom") return "Detik";
  if (m.toLowerCase().startsWith("advertorial ")) m = m.slice(12);

  // Hapus ekstensi web hanya di tampilan (.co.id, .com, .id, .co, .tv, dll)
  m = m.replace(/\.(co\.id|com|id|co|tv|org|net)$/i, "");
  
  // Normalisasi kapitalisasi umum
  if (m.toLowerCase() === "antaranews") return "Antaranews";
  if (m.toLowerCase() === "kumparan") return "Kumparan";
  if (m.toLowerCase() === "kompas") return "Kompas";
  if (m.toLowerCase() === "republika") return "Republika";
  if (m.toLowerCase() === "kontan") return "Kontan";
  if (m.toLowerCase() === "liputan6") return "Liputan6";
  if (m.toLowerCase() === "medcom") return "Medcom";
  if (m.toLowerCase() === "viva") return "VIVA";
  if (m.toLowerCase() === "bisnis") return "Bisnis Indonesia";
  if (m.toLowerCase() === "tempo") return "Tempo";

  return m;
}

export function formatShortDate(dateStr: string): string {
  if (!dateStr) return "";
  try {
    const parts = dateStr.slice(0, 10).split("-");
    if (parts.length === 3) {
      const year = parts[0];
      const monthIdx = parseInt(parts[1], 10);
      const day = parseInt(parts[2], 10);
      const months = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agt", "Sep", "Okt", "Nov", "Des"];
      return `${day} ${months[monthIdx]} ${year}`;
    }
  } catch {
    // fallback
  }
  return dateStr;
}
