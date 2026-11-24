import test from "node:test";
import assert from "node:assert/strict";

function sortArticles(articles, sortBy) {
  const list = [...articles];
  const getSortKey = (a) => a.datetime || `${a.date || ""}T${a.time || "00:00"}`;

  if (sortBy === "terbaru") {
    list.sort(
      (a, b) =>
        getSortKey(b).localeCompare(getSortKey(a)) ||
        String(b.id).localeCompare(String(a.id))
    );
  } else if (sortBy === "terlama") {
    list.sort(
      (a, b) =>
        getSortKey(a).localeCompare(getSortKey(b)) ||
        String(a.id).localeCompare(String(b.id))
    );
  } else if (sortBy === "media") {
    list.sort((a, b) => (a.media || "").localeCompare(b.media || ""));
  }
  return list;
}

test("HalamanBerita sorting: artikel 21 Nov 09:00 harus lebih baru dari 19 Nov 23:00", () => {
  const sample = [
    {
      id: "art_bbb222",
      title: "Berita 19 Nov Malam",
      date: "2026-11-19",
      time: "23:00",
      datetime: "2026-11-19T23:00:00",
      media: "Kompas",
    },
    {
      id: "art_aaa111",
      title: "Berita 21 Nov Pagi",
      date: "2026-11-21",
      time: "09:00",
      datetime: "2026-11-21T09:00:00",
      media: "Detik",
    },
    {
      id: "art_ccc333",
      title: "Berita 20 Nov Siang",
      date: "2026-11-20",
      time: "12:00",
      datetime: "2026-11-20T12:00:00",
      media: "Antara",
    },
  ];

  // Mode terbaru (descending)
  const sortedDesc = sortArticles(sample, "terbaru");
  assert.equal(sortedDesc[0].id, "art_aaa111", "21 Nov 09:00 harus posisi pertama");
  assert.equal(sortedDesc[1].id, "art_ccc333", "20 Nov 12:00 harus posisi kedua");
  assert.equal(sortedDesc[2].id, "art_bbb222", "19 Nov 23:00 harus posisi ketiga");

  // Mode terlama (ascending)
  const sortedAsc = sortArticles(sample, "terlama");
  assert.equal(sortedAsc[0].id, "art_bbb222", "19 Nov 23:00 harus pertama");
  assert.equal(sortedAsc[1].id, "art_ccc333", "20 Nov 12:00 harus kedua");
  assert.equal(sortedAsc[2].id, "art_aaa111", "21 Nov 09:00 harus ketiga");
});

test("HalamanBerita sorting: fallback ke (date, time) jika datetime tidak ada", () => {
  const sample = [
    {
      id: "art_2",
      title: "Tanpa datetime 19 Nov 23:00",
      date: "2026-11-19",
      time: "23:00",
    },
    {
      id: "art_1",
      title: "Tanpa datetime 21 Nov 09:00",
      date: "2026-11-21",
      time: "09:00",
    },
  ];

  const sorted = sortArticles(sample, "terbaru");
  assert.equal(sorted[0].id, "art_1", "21 Nov harus lebih baru dari 19 Nov meski tanpa datetime");
  assert.equal(sorted[1].id, "art_2");
});

test("HalamanBerita sorting: id hash sebagai tiebreaker deterministik untuk datetime sama", () => {
  const sample = [
    { id: "art_zzz999", datetime: "2026-11-21T10:00:00" },
    { id: "art_aaa000", datetime: "2026-11-21T10:00:00" },
  ];

  const sorted = sortArticles(sample, "terbaru");
  assert.equal(sorted[0].id, "art_zzz999");
  assert.equal(sorted[1].id, "art_aaa000");
});
