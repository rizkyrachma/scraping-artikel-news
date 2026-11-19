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
  ChevronDown,
  ChevronUp,
  RotateCcw,
  Calendar,
  ArrowUpDown,
  FileText,
  Layers
} from "lucide-react";
import PageHeaderCard from "@/components/PageHeaderCard";
import CustomSelect, { CustomSelectOption } from "@/components/ui/CustomSelect";
import { Article, SummaryData } from "@/lib/types";
import { formatNumberIndo, normalizeTitle, normalizeMedia, formatShortDate } from "@/lib/utils";

interface HalamanBeritaProps {
  summaryData: SummaryData | null;
  selectedDate?: string;
  onSelectDate?: (date: string) => void;
  selectedTone?: string;
  onSelectTone?: (tone: string) => void;
  cachedArticles?: Article[];
  onArticlesLoaded?: (articles: Article[]) => void;
}

const ITEMS_PER_PAGE = 24;
const GROUPS_PER_PAGE = 12;
const LARGE_GROUP_THRESHOLD = 12;
const GROUP_ITEMS_PER_PAGE = 12;

interface IssueGroup {
  isu: string;
  isNoIssueGroup: boolean;
  items: Article[];
  mediaList: string[];
  tone: Article["tone"];
  isMixedTone: boolean;
  sumberIsu?: string;
}

function getToneClasses(tone: Article["tone"]) {
  if (tone === "Positif") {
    return { border: "tone-border-pos", badge: "badge-tone-pos" };
  }
  if (tone === "Negatif") {
    return { border: "tone-border-neg", badge: "badge-tone-neg" };
  }
  return { border: "tone-border-net", badge: "badge-tone-net" };
}

function resolveGroupTone(items: Article[]): { tone: Article["tone"]; isMixed: boolean } {
  const counts: Record<Article["tone"], number> = { Positif: 0, Netral: 0, Negatif: 0 };
  for (const it of items) {
    const t = it.tone === "Positif" || it.tone === "Negatif" ? it.tone : "Netral";
    counts[t] += 1;
  }
  const distinct = (Object.keys(counts) as Article["tone"][]).filter((k) => counts[k] > 0);
  let best: Article["tone"] = "Netral";
  let bestCount = -1;
  for (const t of ["Negatif", "Positif", "Netral"] as Article["tone"][]) {
    if (counts[t] > bestCount) {
      best = t;
      bestCount = counts[t];
    }
  }
  return { tone: best, isMixed: distinct.length > 1 };
}

export default function HalamanBerita({
  summaryData,
  selectedDate: propSelectedDate,
  onSelectDate,
  selectedTone: propSelectedTone,
  onSelectTone,
  cachedArticles,
  onArticlesLoaded,
}: HalamanBeritaProps) {
  // State data artikel
  const [articles, setArticles] = useState<Article[]>(() => cachedArticles || []);
  const [isLoading, setIsLoading] = useState(!cachedArticles || cachedArticles.length === 0);
  const [isError, setIsError] = useState(false);

  // State filter
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [selectedTone, setSelectedTone] = useState<string>(propSelectedTone || "Semua");
  const [selectedCommodity, setSelectedCommodity] = useState<string>("Semua");
  const [selectedSpokesperson, setSelectedSpokesperson] = useState<string>("Semua");
  const [selectedDate, setSelectedDate] = useState<string>(propSelectedDate || "Semua");
  const [sortBy, setSortBy] = useState<"terbaru" | "terlama" | "media">("terbaru");
  const [groupByIsu, setGroupByIsu] = useState<boolean>(false);

  // State paginasi & grup besar
  const [currentPage, setCurrentPage] = useState(1);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
  const [groupPages, setGroupPages] = useState<Record<string, number>>({});

  // Sinkronisasi tanggal dari prop luar (misal klik dari kalender/ringkasan)
  useEffect(() => {
    if (propSelectedDate !== undefined && propSelectedDate !== selectedDate) {
      setSelectedDate(propSelectedDate || "Semua");
      setCurrentPage(1);
      setGroupPages({});
    }
  }, [propSelectedDate, selectedDate]);

  // Sinkronisasi tone dari prop luar (misal klik legend Pos/Net/Neg di ringkasan)
  useEffect(() => {
    if (propSelectedTone !== undefined && propSelectedTone !== selectedTone) {
      setSelectedTone(propSelectedTone || "Semua");
      setCurrentPage(1);
      setGroupPages({});
    }
  }, [propSelectedTone, selectedTone]);

  // Debounce search 300ms
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery.trim());
      setCurrentPage(1);
      setGroupPages({});
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Muat data artikel lengkap (articles_all.json via /api/data untuk sinkronisasi live)
  useEffect(() => {
    if (cachedArticles && cachedArticles.length > 0) {
      setArticles(cachedArticles);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    fetch(`/api/data/articles_all.json?t=${Date.now()}`, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error("Gagal mengambil articles_all.json");
        return res.json();
      })
      .then((data: Article[]) => {
        setArticles(data);
        onArticlesLoaded?.(data);
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
  }, [summaryData, cachedArticles, onArticlesLoaded]);

  // Reset page saat filter berubah
  const handleFilterChange = (setter: (val: string) => void, val: string) => {
    setter(val);
    setCurrentPage(1);
    setGroupPages({});
  };

  const handleToneChange = (val: string) => {
    setSelectedTone(val);
    onSelectTone?.(val);
    setCurrentPage(1);
    setGroupPages({});
  };

  const handleDateChange = (val: string) => {
    setSelectedDate(val);
    onSelectDate?.(val);
    setCurrentPage(1);
    setGroupPages({});
  };

  const handleResetFilters = () => {
    setSearchQuery("");
    setDebouncedSearch("");
    setSelectedTone("Semua");
    onSelectTone?.("Semua");
    setSelectedCommodity("Semua");
    setSelectedSpokesperson("Semua");
    setSelectedDate("Semua");
    onSelectDate?.("Semua");
    setSortBy("terbaru");
    setCurrentPage(1);
    setGroupPages({});
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
        const iMatch = art.isu ? art.isu.toLowerCase().includes(q) : false;
        if (!tMatch && !mMatch && !sMatch && !iMatch) return false;
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

  // Pengelompokan per isu saat mode aktif
  const issueGroups: IssueGroup[] = useMemo(() => {
    if (!groupByIsu) return [];
    const groupedMap = new Map<string, Article[]>();
    const noIssueItems: Article[] = [];
    for (const art of sortedArticles) {
      const isuName = (art.isu || "").trim();
      if (!isuName) {
        noIssueItems.push(art);
        continue;
      }
      const existing = groupedMap.get(isuName);
      if (existing) {
        existing.push(art);
      } else {
        groupedMap.set(isuName, [art]);
      }
    }
    const buildGroup = (isuLabel: string, items: Article[], isNoIssueGroup: boolean): IssueGroup => {
      const mediaSeen = new Set<string>();
      const mediaList: string[] = [];
      let sumberIsu: string | undefined;
      for (const item of items) {
        const med = normalizeMedia(item.media);
        if (med && !mediaSeen.has(med)) {
          mediaSeen.add(med);
          mediaList.push(med);
        }
        if (!sumberIsu && item.sumber_isu) {
          sumberIsu = item.sumber_isu;
        }
      }
      const { tone, isMixed } = resolveGroupTone(items);
      return { isu: isuLabel, isNoIssueGroup, items, mediaList, tone, isMixedTone: isMixed, sumberIsu };
    };
    const out: IssueGroup[] = [];
    groupedMap.forEach((items, isuName) => out.push(buildGroup(isuName, items, false)));
    if (noIssueItems.length > 0) {
      out.push(buildGroup("Tanpa isu", noIssueItems, true));
    }
    return out;
  }, [sortedArticles, groupByIsu]);

  // Paginasi (per artikel atau per grup isu sesuai mode)
  const totalCount = sortedArticles.length;
  const totalGroups = issueGroups.length;
  const pageSize = groupByIsu ? GROUPS_PER_PAGE : ITEMS_PER_PAGE;
  const totalItemsForPaging = groupByIsu ? totalGroups : totalCount;
  const totalPages = Math.max(1, Math.ceil(totalItemsForPaging / pageSize));
  const startIndex = (currentPage - 1) * pageSize;
  const endIndex = Math.min(startIndex + pageSize, totalItemsForPaging);
  const currentArticles = useMemo(() => {
    return groupByIsu ? [] : sortedArticles.slice(startIndex, endIndex);
  }, [sortedArticles, startIndex, endIndex, groupByIsu]);
  const currentGroups = useMemo(() => {
    return groupByIsu ? issueGroups.slice(startIndex, endIndex) : [];
  }, [issueGroups, startIndex, endIndex, groupByIsu]);

  const renderArticleCard = (art: Article) => {
    const { border: toneClass, badge: badgeToneClass } = getToneClasses(art.tone);
    const isNoCommodity = !art.commodity || art.commodity === "Lainnya";
    const displayCommodity = isNoCommodity ? "Tanpa komoditas" : art.commodity;
    const isuText = (art.isu || "").trim();
    const alasanTone = (art.alasan_tone || "").trim();
    const hasMeta = Boolean(isuText || alasanTone);

    return (
      <a
        key={art.id}
        href={art.link}
        target="_blank"
        rel="noopener noreferrer"
        className={`news-card-uniform ${toneClass}${hasMeta ? " news-card-has-meta" : ""}`}
        title="Klik untuk membuka berita di tab baru"
      >
        {/* Header Kartu: Badge Tone + External Icon */}
        <div className="news-card-top">
          <span
            className={`badge-tone ${badgeToneClass}`}
            title={alasanTone ? `Alasan tone: ${alasanTone}` : undefined}
          >
            {art.tone}
          </span>
          <span className="card-external-icon">
            <ExternalLink size={13} />
          </span>
        </div>

        {/* Label Isu kecil (disembunyikan bila kosong) */}
        {isuText && (
          <div className="news-card-isu-label" title={`Isu: ${isuText}`}>
            <Layers size={10} className="isu-label-icon" />
            <span className="isu-label-text">{isuText}</span>
          </div>
        )}

        {/* Judul Berita: maks 3 baris, normalisasi huruf kapital */}
        <h3 className="news-card-headline" title={art.title}>
          {normalizeTitle(art.title)}
        </h3>

        {/* Teks bantu Alasan Tone (opsional, non-dominan) */}
        {alasanTone && (
          <p className="news-card-tone-reason" title={alasanTone}>
            {alasanTone}
          </p>
        )}

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
  };

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
        description={
          selectedDate && selectedDate !== "Semua"
            ? `Menampilkan arsip berita tanggal ${formatShortDate(selectedDate)} (${formatNumberIndo(filteredArticles.length)} berita terpilih dari total ${formatNumberIndo(articles.length || summaryData?.metadata?.total_articles || 0)} berita sektor agro terverifikasi).`
            : `Pencarian, pemfilteran komoditas, dan pemantauan sentimen dari ${formatNumberIndo(articles.length || summaryData?.metadata?.total_articles || 0)} berita sektor agro terverifikasi.`
        }
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
                  onClick={() => handleToneChange(t)}
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
              onChange={(val) => handleDateChange(val)}
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

            {/* Toggle Mode Kelompokkan per isu (default MATI) */}
            <button
              type="button"
              aria-pressed={groupByIsu}
              onClick={() => {
                setGroupByIsu((prev) => !prev);
                setCurrentPage(1);
              }}
              className={`btn-group-toggle ${groupByIsu ? "active" : ""}`}
              title="Kelompokkan daftar berita berdasarkan nama isu"
            >
              <Layers size={13} />
              <span>Kelompokkan per isu</span>
            </button>
          </div>
        </div>

        {/* 3. Baris Ringkasan Hasil & Filter Aktif */}
        <div className="news-results-bar">
          <div className="results-count-text">
            {totalCount > 0 ? (
              groupByIsu ? (
                <>
                  Menampilkan <strong>{formatNumberIndo(startIndex + 1)}–{formatNumberIndo(endIndex)}</strong> dari <strong>{formatNumberIndo(totalGroups)}</strong> isu ({formatNumberIndo(totalCount)} berita)
                </>
              ) : (
                <>
                  Menampilkan <strong>{formatNumberIndo(startIndex + 1)}–{formatNumberIndo(endIndex)}</strong> dari <strong>{formatNumberIndo(totalCount)}</strong> berita
                </>
              )
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
                <button type="button" onClick={() => handleToneChange("Semua")}>✕</button>
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
                <button type="button" onClick={() => handleDateChange("Semua")}>✕</button>
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
          ) : totalCount === 0 ? (
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
          ) : groupByIsu ? (
            // Tampilan Terkelompok per Isu
            <div className="issue-groups-list">
              {currentGroups.map((group) => {
                const { badge: groupBadgeClass } = getToneClasses(group.tone);
                const mediaPreview =
                  group.mediaList.length > 5
                    ? `${group.mediaList.slice(0, 5).join(", ")} +${group.mediaList.length - 5} lainnya`
                    : group.mediaList.join(", ");
                const isLargeGroup = group.items.length > LARGE_GROUP_THRESHOLD;
                const isExpanded = isLargeGroup ? Boolean(expandedGroups[group.isu]) : true;
                const subTotalPages = Math.max(1, Math.ceil(group.items.length / GROUP_ITEMS_PER_PAGE));
                const subPage = Math.min(groupPages[group.isu] || 1, subTotalPages);
                const subStart = (subPage - 1) * GROUP_ITEMS_PER_PAGE;
                const visibleItems = isLargeGroup
                  ? group.items.slice(subStart, subStart + GROUP_ITEMS_PER_PAGE)
                  : group.items;

                return (
                  <section key={group.isu} className="issue-group-section">
                    <header className="issue-group-header">
                      <div className="issue-group-header-top">
                        <div className="issue-group-title-row">
                          {group.isNoIssueGroup ? (
                            <span className="issue-neutral-note">Tone dinilai per berita</span>
                          ) : (
                            <span className={`badge-tone ${groupBadgeClass}`}>
                              {group.tone}
                              {group.isMixedTone ? " (Mayoritas)" : ""}
                            </span>
                          )}
                          <h3 className="issue-group-name">{group.isu}</h3>
                          {group.sumberIsu === "rilis" && (
                            <span className="issue-source-tag">Rilis</span>
                          )}
                        </div>
                        {isLargeGroup && (
                          <button
                            type="button"
                            aria-expanded={isExpanded}
                            onClick={() =>
                              setExpandedGroups((prev) => ({ ...prev, [group.isu]: !isExpanded }))
                            }
                            className="issue-group-expand-btn"
                          >
                            {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                            <span>
                              {isExpanded
                                ? "Tutup daftar"
                                : `Tampilkan (${formatNumberIndo(group.items.length)} berita)`}
                            </span>
                          </button>
                        )}
                      </div>
                      <div className="issue-group-meta">
                        <span className="issue-group-count">
                          {formatNumberIndo(group.items.length)} berita
                        </span>
                        <span className="meta-dot-sep">•</span>
                        <span
                          className="issue-group-media"
                          title={group.mediaList.join(", ")}
                        >
                          Media: {mediaPreview || "-"}
                        </span>
                      </div>
                    </header>
                    {isExpanded && (
                      <>
                        <div className="news-grid-uniform">
                          {visibleItems.map((art) => renderArticleCard(art))}
                        </div>
                        {isLargeGroup && subTotalPages > 1 && (
                          <div className="issue-subpage-bar">
                            <button
                              type="button"
                              disabled={subPage <= 1}
                              onClick={() =>
                                setGroupPages((prev) => ({
                                  ...prev,
                                  [group.isu]: Math.max(1, subPage - 1),
                                }))
                              }
                              className="pagination-btn"
                            >
                              <ChevronLeft size={14} />
                              <span>Sebelumnya</span>
                            </button>
                            <span className="issue-subpage-info">
                              Hal <strong>{subPage}</strong>/{formatNumberIndo(subTotalPages)} (
                              {formatNumberIndo(subStart + 1)}–
                              {formatNumberIndo(Math.min(subStart + GROUP_ITEMS_PER_PAGE, group.items.length))} dari{" "}
                              {formatNumberIndo(group.items.length)})
                            </span>
                            <button
                              type="button"
                              disabled={subPage >= subTotalPages}
                              onClick={() =>
                                setGroupPages((prev) => ({
                                  ...prev,
                                  [group.isu]: Math.min(subTotalPages, subPage + 1),
                                }))
                              }
                              className="pagination-btn"
                            >
                              <span>Berikutnya</span>
                              <ChevronRight size={14} />
                            </button>
                          </div>
                        )}
                      </>
                    )}
                  </section>
                );
              })}
            </div>
          ) : (
            // Grid Kartu Berita Seragam (default)
            <div className="news-grid-uniform">
              {currentArticles.map((art) => renderArticleCard(art))}
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
