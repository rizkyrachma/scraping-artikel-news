"use client";

import React, { useState, useEffect, useMemo, useRef } from "react";
import {
  Search,
  Filter,
  Tag,
  User,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  RotateCcw,
  Calendar,
  ArrowUpDown,
  FileText
} from "lucide-react";
import PageHeaderCard from "@/components/PageHeaderCard";
import CustomSelect, { CustomSelectOption } from "@/components/ui/CustomSelect";
import { Article, SummaryData } from "@/lib/types";
import { formatNumberIndo, normalizeTitle, normalizeMedia, formatShortDate } from "@/lib/utils";

interface HalamanBeritaProps {
  summaryData: SummaryData | null;
}

const ITEMS_PER_PAGE = 24;

export default function HalamanBerita({ summaryData }: HalamanBeritaProps) {
  // State data artikel
  const [articles, setArticles] = useState<Article[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isError, setIsError] = useState(false);

  // State filter
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [selectedTone, setSelectedTone] = useState<string>("Semua");
  const [selectedCommodity, setSelectedCommodity] = useState<string>("Semua");
  const [selectedSpokesperson, setSelectedSpokesperson] = useState<string>("Semua");
  const [selectedDate, setSelectedDate] = useState<string>("Semua");
  const [sortBy, setSortBy] = useState<"terbaru" | "terlama" | "media">("terbaru");

  // State paginasi
  const [currentPage, setCurrentPage] = useState(1);

  // Debounce search 300ms
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery.trim());
      setCurrentPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Muat data artikel lengkap (articles_all.json)
  useEffect(() => {
    setIsLoading(true);
    fetch("/data/articles_all.json")
      .then((res) => {
        if (!res.ok) throw new Error("Gagal mengambil articles_all.json");
        return res.json();
      })
      .then((data: Article[]) => {
        setArticles(data);
        setIsLoading(false);
      })
      .catch((err) => {
        console.warn("Fallback ke recent_articles:", err);
        if (summaryData?.recent_articles) {
          setArticles(summaryData.recent_articles);
        } else {
          setIsError(true);
        }
        setIsLoading(false);
      });
  }, [summaryData]);

  // Reset page saat filter berubah
  const handleFilterChange = (setter: (val: string) => void, val: string) => {
    setter(val);
    setCurrentPage(1);
  };

  const handleResetFilters = () => {
    setSearchQuery("");
    setDebouncedSearch("");
    setSelectedTone("Semua");
    setSelectedCommodity("Semua");
    setSelectedSpokesperson("Semua");
    setSelectedDate("Semua");
    setSortBy("terbaru");
    setCurrentPage(1);
  };

  // Daftar opsi unik untuk dropdown
  const commodityOptions = useMemo(() => {
    if (summaryData?.commodities) {
      return summaryData.commodities.map((c) => ({
        label: c.name === "Lainnya" ? "Tanpa komoditas spesifik" : c.name,
        value: c.name,
        count: c.count,
      }));
    }
    const set = new Set<string>();
    articles.forEach((a) => {
      if (a.commodity) set.add(a.commodity);
    });
    return Array.from(set).map((c) => ({
      label: c === "Lainnya" ? "Tanpa komoditas spesifik" : c,
      value: c,
      count: 0,
    }));
  }, [summaryData, articles]);

  const spokespersonOptions = useMemo(() => {
    if (summaryData?.spokespersons) {
      return summaryData.spokespersons
        .filter((s) => s.name && s.count > 0)
        .map((s) => ({ label: s.name, value: s.name, count: s.count }));
    }
    const set = new Set<string>();
    articles.forEach((a) => {
      if (a.spokesperson) set.add(a.spokesperson);
    });
    return Array.from(set).map((s) => ({ label: s, value: s, count: 0 }));
  }, [summaryData, articles]);

  // Daftar tanggal unik (dari summary recent_days atau articles)
  const dateOptions = useMemo(() => {
    if (summaryData?.metadata?.calendar_counts) {
      return Object.keys(summaryData.metadata.calendar_counts).sort().reverse();
    }
    const set = new Set<string>();
    articles.forEach((a) => {
      if (a.date) set.add(a.date);
    });
    return Array.from(set).sort().reverse();
  }, [summaryData, articles]);

  // Opsi terformat untuk CustomSelect
  const customCommodityOptions: CustomSelectOption[] = useMemo(() => {
    return [
      { label: "Semua Komoditas", value: "Semua", isAll: true },
      ...commodityOptions.map((c) => ({
        label: c.label,
        value: c.value,
        count: c.count ? formatNumberIndo(c.count) : undefined,
      })),
    ];
  }, [commodityOptions]);

  const customSpokespersonOptions: CustomSelectOption[] = useMemo(() => {
    return [
      { label: "Semua Tokoh", value: "Semua", isAll: true },
      ...spokespersonOptions.map((s) => ({
        label: s.label,
        value: s.value,
        count: s.count ? formatNumberIndo(s.count) : undefined,
      })),
    ];
  }, [spokespersonOptions]);

  const customDateOptions: CustomSelectOption[] = useMemo(() => {
    return [
      { label: "Semua Tanggal", value: "Semua", isAll: true },
      ...dateOptions.map((d) => {
        const cnt = summaryData?.metadata?.calendar_counts?.[d];
        return {
          label: formatShortDate(d),
          value: d,
          count: cnt ? formatNumberIndo(cnt) : undefined,
        };
      }),
    ];
  }, [dateOptions, summaryData]);

  const customSortOptions: CustomSelectOption[] = useMemo(
    () => [
      { label: "Terbaru", value: "terbaru" },
      { label: "Terlama", value: "terlama" },
      { label: "Media (A-Z)", value: "media" },
    ],
    []
  );

  // Filtering data
  const filteredArticles = useMemo(() => {
    return articles.filter((art) => {
      // 1. Pencarian teks
      if (debouncedSearch) {
        const q = debouncedSearch.toLowerCase();
        const tMatch = art.title.toLowerCase().includes(q);
        const mMatch = art.media.toLowerCase().includes(q);
        const sMatch = art.spokesperson ? art.spokesperson.toLowerCase().includes(q) : false;
        if (!tMatch && !mMatch && !sMatch) return false;
      }

      // 2. Tone
      if (selectedTone !== "Semua" && art.tone !== selectedTone) {
        return false;
      }

      // 3. Komoditas
      if (selectedCommodity !== "Semua" && art.commodity !== selectedCommodity) {
        return false;
      }

      // 4. Tokoh
      if (selectedSpokesperson !== "Semua" && art.spokesperson !== selectedSpokesperson) {
        return false;
      }

      // 5. Tanggal
      if (selectedDate !== "Semua" && art.date !== selectedDate) {
        return false;
      }

      return true;
    });
  }, [articles, debouncedSearch, selectedTone, selectedCommodity, selectedSpokesperson, selectedDate]);

  // Pengurutan (Sorting)
  const sortedArticles = useMemo(() => {
    const list = [...filteredArticles];
    if (sortBy === "terbaru") {
      list.sort((a, b) => (b.date || "").localeCompare(a.date || "") || b.id - a.id);
    } else if (sortBy === "terlama") {
      list.sort((a, b) => (a.date || "").localeCompare(b.date || "") || a.id - b.id);
    } else if (sortBy === "media") {
      list.sort((a, b) => a.media.localeCompare(b.media));
    }
    return list;
  }, [filteredArticles, sortBy]);

  // Paginasi
  const totalCount = sortedArticles.length;
  const totalPages = Math.max(1, Math.ceil(totalCount / ITEMS_PER_PAGE));
  const startIndex = (currentPage - 1) * ITEMS_PER_PAGE;
  const endIndex = Math.min(startIndex + ITEMS_PER_PAGE, totalCount);
  const currentArticles = useMemo(() => {
    return sortedArticles.slice(startIndex, endIndex);
  }, [sortedArticles, startIndex, endIndex]);

  // Cek apakah ada filter aktif
  const hasActiveFilters =
    Boolean(debouncedSearch) ||
    selectedTone !== "Semua" ||
    selectedCommodity !== "Semua" ||
    selectedSpokesperson !== "Semua" ||
    selectedDate !== "Semua";

  return (
    <main className="full-tab-container">
      {/* 1. Header Kartu Halaman Berita */}
      <PageHeaderCard
        title="Arsip Berita Industri Agro"
        description={`Pencarian, pemfilteran komoditas, dan pemantauan sentimen dari ${formatNumberIndo(articles.length || 4127)} berita sektor agro terverifikasi.`}
      />

      {/* 2. Kartu Utama Halaman Berita */}
      <div className="tab-main-card">
        {/* Toolbar Filter & Pencarian */}
        <div className="news-toolbar-wrap">
          {/* Baris Atas: Input Pencarian & Segmented Tone */}
          <div className="news-toolbar-primary">
            {/* Input Pencarian dengan ikon terintegrasi */}
            <div className="search-field-box">
              <Search size={15} className="search-field-icon" />
              <input
                type="text"
                placeholder="Cari judul berita, media, atau nama tokoh..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="search-field-input"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery("")}
                  className="search-clear-btn"
                  title="Hapus pencarian"
                >
                  ✕
                </button>
              )}
            </div>

            {/* Segmented Chip Filter Tone */}
            <div className="tone-segmented-group">
              {["Semua", "Positif", "Netral", "Negatif"].map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => handleFilterChange(setSelectedTone, t)}
                  className={`tone-chip ${selectedTone === t ? "active" : ""} tone-chip-${t.toLowerCase()}`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          {/* Baris Bawah: Dropdown Komoditas, Tokoh, Tanggal, dan Pengurutan */}
          <div className="news-toolbar-secondary">
            {/* Dropdown Komoditas */}
            <CustomSelect
              value={selectedCommodity}
              onChange={(val) => handleFilterChange(setSelectedCommodity, val)}
              options={customCommodityOptions}
              icon={<Tag size={13} />}
              ariaLabel="Filter Komoditas"
              placeholder="Semua Komoditas"
              searchable={true}
              searchPlaceholder="Cari komoditas..."
            />

            {/* Dropdown Tokoh */}
            <CustomSelect
              value={selectedSpokesperson}
              onChange={(val) => handleFilterChange(setSelectedSpokesperson, val)}
              options={customSpokespersonOptions}
              icon={<User size={13} />}
              ariaLabel="Filter Tokoh"
              placeholder="Semua Tokoh"
              searchable={true}
              searchPlaceholder="Cari tokoh..."
            />

            {/* Dropdown Tanggal */}
            <CustomSelect
              value={selectedDate}
              onChange={(val) => handleFilterChange(setSelectedDate, val)}
              options={customDateOptions}
              icon={<Calendar size={13} />}
              ariaLabel="Filter Tanggal Berita"
              placeholder="Semua Tanggal"
            />

            {/* Dropdown Pengurutan */}
            <CustomSelect
              value={sortBy}
              onChange={(val) => setSortBy(val as any)}
              options={customSortOptions}
              icon={<ArrowUpDown size={13} />}
              ariaLabel="Pengurutan Berita"
              placeholder="Urutkan"
            />
          </div>
        </div>

        {/* 3. Baris Ringkasan Hasil & Filter Aktif */}
        <div className="news-results-bar">
          <div className="results-count-text">
            {totalCount > 0 ? (
              <>
                Menampilkan <strong>{formatNumberIndo(startIndex + 1)}–{formatNumberIndo(endIndex)}</strong> dari <strong>{formatNumberIndo(totalCount)}</strong> berita
              </>
            ) : (
              <span>Menampilkan <strong>0</strong> berita</span>
            )}
          </div>

          {/* Active Filter Chips */}
          <div className="active-filters-list">
            {debouncedSearch && (
              <span className="active-chip">
                Cari: &ldquo;{debouncedSearch}&rdquo;
                <button type="button" onClick={() => setSearchQuery("")}>✕</button>
              </span>
            )}
            {selectedTone !== "Semua" && (
              <span className="active-chip">
                Tone: {selectedTone}
                <button type="button" onClick={() => setSelectedTone("Semua")}>✕</button>
              </span>
            )}
            {selectedCommodity !== "Semua" && (
              <span className="active-chip">
                Komoditas: {selectedCommodity === "Lainnya" ? "Tanpa komoditas" : selectedCommodity}
                <button type="button" onClick={() => setSelectedCommodity("Semua")}>✕</button>
              </span>
            )}
            {selectedSpokesperson !== "Semua" && (
              <span className="active-chip">
                Tokoh: {selectedSpokesperson}
                <button type="button" onClick={() => setSelectedSpokesperson("Semua")}>✕</button>
              </span>
            )}
            {selectedDate !== "Semua" && (
              <span className="active-chip">
                Tanggal: {formatShortDate(selectedDate)}
                <button type="button" onClick={() => setSelectedDate("Semua")}>✕</button>
              </span>
            )}
            {hasActiveFilters && (
              <button
                type="button"
                onClick={handleResetFilters}
                className="btn-reset-filters"
              >
                <RotateCcw size={12} />
                <span>Reset filter</span>
              </button>
            )}
          </div>
        </div>

        {/* 4. Area Konten Berita (Scroll Internal) */}
        <div className="news-cards-viewport custom-scrollbar">
          {isLoading ? (
            // Loading Skeleton
            <div className="news-skeleton-grid">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="news-card-skeleton animate-pulse" />
              ))}
            </div>
          ) : isError ? (
            // Error State
            <div className="state-empty-box">
              <FileText size={40} className="text-slate-400" />
              <h3 className="empty-title">Gagal Memuat Berita</h3>
              <p className="empty-desc">Terjadi kendala saat membaca dataset artikel. Silakan muat ulang halaman.</p>
              <button type="button" onClick={() => window.location.reload()} className="btn-action-refresh">
                Muat Ulang
              </button>
            </div>
          ) : currentArticles.length === 0 ? (
            // Empty State
            <div className="state-empty-box">
              <FileText size={44} className="text-slate-400" />
              <h3 className="empty-title">Tidak Ada Berita yang Cocok</h3>
              <p className="empty-desc">
                Tidak ditemukan artikel dengan kriteria filter saat ini. Coba ubah kata kunci atau reset filter pencarian.
              </p>
              <button type="button" onClick={handleResetFilters} className="btn-action-refresh">
                <RotateCcw size={13} />
                <span>Reset Filter</span>
              </button>
            </div>
          ) : (
            // Grid Kartu Berita Seragam
            <div className="news-grid-uniform">
              {currentArticles.map((art) => {
                const toneClass =
                  art.tone === "Positif"
                    ? "tone-border-pos"
                    : art.tone === "Negatif"
                    ? "tone-border-neg"
                    : "tone-border-net";

                const badgeToneClass =
                  art.tone === "Positif"
                    ? "badge-tone-pos"
                    : art.tone === "Negatif"
                    ? "badge-tone-neg"
                    : "badge-tone-net";

                const isNoCommodity = !art.commodity || art.commodity === "Lainnya";
                const displayCommodity = isNoCommodity ? "Tanpa komoditas" : art.commodity;

                return (
                  <a
                    key={art.id}
                    href={art.link}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`news-card-uniform ${toneClass}`}
                    title="Klik untuk membuka berita di tab baru"
                  >
                    {/* Header Kartu: Badge Tone + External Icon */}
                    <div className="news-card-top">
                      <span className={`badge-tone ${badgeToneClass}`}>
                        {art.tone}
                      </span>
                      <span className="card-external-icon">
                        <ExternalLink size={13} />
                      </span>
                    </div>

                    {/* Judul Berita: maks 3 baris, normalisasi huruf kapital */}
                    <h3 className="news-card-headline" title={art.title}>
                      {normalizeTitle(art.title)}
                    </h3>

                    {/* Meta satu baris: Media + Tanggal Pendek (Truncate) */}
                    <div className="news-card-meta-line" title={`${art.media} • ${formatShortDate(art.date)}`}>
                      <span className="meta-media-name">{normalizeMedia(art.media)}</span>
                      <span className="meta-dot-sep">•</span>
                      <span className="meta-date-text">{formatShortDate(art.date)}</span>
                    </div>

                    {/* Footer Kartu: Tag Komoditas & Tokoh */}
                    <div className="news-card-tags-row">
                      <span className={`tag-item tag-commodity ${isNoCommodity ? "tag-muted" : ""}`}>
                        <Tag size={10} className="tag-icon" />
                        <span className="tag-text">{displayCommodity}</span>
                      </span>

                      {art.spokesperson && (
                        <span className="tag-item tag-spokesperson" title={`Tokoh: ${art.spokesperson}`}>
                          <User size={10} className="tag-icon" />
                          <span className="tag-text">{art.spokesperson}</span>
                        </span>
                      )}
                    </div>
                  </a>
                );
              })}
            </div>
          )}
        </div>

        {/* 5. Footer Paginasi Sticky */}
        {totalCount > 0 && (
          <div className="news-pagination-bar">
            <button
              type="button"
              disabled={currentPage <= 1}
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              className="pagination-btn"
            >
              <ChevronLeft size={15} />
              <span>Sebelumnya</span>
            </button>

            <span className="pagination-info">
              Halaman <strong>{currentPage}</strong> dari <strong>{totalPages}</strong>
            </span>

            <button
              type="button"
              disabled={currentPage >= totalPages}
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              className="pagination-btn"
            >
              <span>Berikutnya</span>
              <ChevronRight size={15} />
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
