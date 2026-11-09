"use client";

import React, {
  useState,
  useRef,
  useEffect,
  useCallback,
  useMemo,
  useId,
} from "react";
import { createPortal } from "react-dom";
import { ChevronDown, Check, Search, X } from "lucide-react";

export interface CustomSelectOption {
  value: string;
  label: string;
  count?: number | string;
  isAll?: boolean;
}

export interface CustomSelectProps {
  value: string;
  onChange: (value: string) => void;
  options: CustomSelectOption[];
  icon?: React.ReactNode;
  placeholder?: string;
  searchable?: boolean;
  searchPlaceholder?: string;
  ariaLabel?: string;
  className?: string;
  align?: "left" | "right";
}

export default function CustomSelect({
  value,
  onChange,
  options,
  icon,
  placeholder = "Pilih opsi...",
  searchable = false,
  searchPlaceholder = "Cari opsi...",
  ariaLabel,
  className = "",
  align = "left",
}: CustomSelectProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(-1);
  const [popoverPos, setPopoverPos] = useState<{
    top: number;
    left: number;
    width: number;
    openUpward: boolean;
  }>({ top: 0, left: 0, width: 200, openUpward: false });

  const [isMobile, setIsMobile] = useState(false);
  const [mounted, setMounted] = useState(false);

  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const optionsListRef = useRef<HTMLDivElement>(null);

  const baseId = useId();
  const listboxId = `custom-select-listbox-${baseId}`;

  // Cek mode mobile (< 768px)
  useEffect(() => {
    setMounted(true);
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 768);
    };
    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, []);

  // Filter opsi berdasarkan pencarian
  const filteredOptions = useMemo(() => {
    if (!searchable || !searchQuery.trim()) return options;
    const q = searchQuery.toLowerCase().trim();
    return options.filter((opt) => opt.label.toLowerCase().includes(q));
  }, [options, searchable, searchQuery]);

  // Temukan opsi terpilih saat ini
  const selectedOption = useMemo(() => {
    return options.find((opt) => opt.value === value) || null;
  }, [options, value]);

  // Hitung posisi popover desktop
  const updatePosition = useCallback(() => {
    if (!triggerRef.current || isMobile) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const panelEstimatedHeight = 290;
    const spaceBelow = window.innerHeight - rect.bottom;
    const spaceAbove = rect.top;

    const openUpward = spaceBelow < panelEstimatedHeight && spaceAbove > spaceBelow;
    const width = Math.max(rect.width, 220);

    let left = rect.left;
    if (align === "right" || left + width > window.innerWidth - 10) {
      left = Math.max(10, rect.right - width);
    }

    const top = openUpward
      ? Math.max(10, rect.top - 6)
      : rect.bottom + 6;

    setPopoverPos({ top, left, width, openUpward });
  }, [isMobile, align]);

  // Buka / Tutup Dropdown
  const handleToggle = () => {
    if (isOpen) {
      handleClose();
    } else {
      updatePosition();
      setIsOpen(true);
      setSearchQuery("");
      const idx = filteredOptions.findIndex((opt) => opt.value === value);
      setActiveIndex(idx >= 0 ? idx : 0);
    }
  };

  const handleClose = useCallback(() => {
    setIsOpen(false);
    setSearchQuery("");
    setActiveIndex(-1);
    if (triggerRef.current) {
      triggerRef.current.focus();
    }
  }, []);

  const handleSelect = useCallback(
    (val: string) => {
      onChange(val);
      handleClose();
    },
    [onChange, handleClose]
  );

  // Auto-focus search input jika dibuka
  useEffect(() => {
    if (isOpen) {
      updatePosition();
      if (searchable && searchInputRef.current) {
        setTimeout(() => searchInputRef.current?.focus(), 50);
      }
    }
  }, [isOpen, searchable, updatePosition]);

  // Scroll otomatis ke active item
  useEffect(() => {
    if (isOpen && activeIndex >= 0 && optionsListRef.current) {
      const activeEl = optionsListRef.current.querySelector(
        `[data-index="${activeIndex}"]`
      ) as HTMLElement | null;
      if (activeEl) {
        activeEl.scrollIntoView({ block: "nearest" });
      }
    }
  }, [isOpen, activeIndex]);

  // Click outside listener
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (e: MouseEvent | TouchEvent) => {
      const target = e.target as Node;
      if (
        triggerRef.current?.contains(target) ||
        panelRef.current?.contains(target)
      ) {
        return;
      }
      handleClose();
    };

    const handleScrollOrResize = () => {
      if (!isMobile) {
        updatePosition();
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("touchstart", handleClickOutside);
    window.addEventListener("resize", handleScrollOrResize);
    window.addEventListener("scroll", handleScrollOrResize, true);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("touchstart", handleClickOutside);
      window.removeEventListener("resize", handleScrollOrResize);
      window.removeEventListener("scroll", handleScrollOrResize, true);
    };
  }, [isOpen, isMobile, handleClose, updatePosition]);

  // Keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen) {
      if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        handleToggle();
      }
      return;
    }

    switch (e.key) {
      case "Escape":
        e.preventDefault();
        handleClose();
        break;
      case "ArrowDown":
        e.preventDefault();
        setActiveIndex((prev) =>
          prev < filteredOptions.length - 1 ? prev + 1 : 0
        );
        break;
      case "ArrowUp":
        e.preventDefault();
        setActiveIndex((prev) =>
          prev > 0 ? prev - 1 : filteredOptions.length - 1
        );
        break;
      case "Home":
        e.preventDefault();
        setActiveIndex(0);
        break;
      case "End":
        e.preventDefault();
        setActiveIndex(filteredOptions.length - 1);
        break;
      case "Enter":
        e.preventDefault();
        if (activeIndex >= 0 && activeIndex < filteredOptions.length) {
          handleSelect(filteredOptions[activeIndex].value);
        }
        break;
      case "Tab":
        handleClose();
        break;
      default:
        // Type-ahead jump jika search bar tidak aktif
        if (!searchable && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
          const char = e.key.toLowerCase();
          const matchIdx = filteredOptions.findIndex((opt) =>
            opt.label.toLowerCase().startsWith(char)
          );
          if (matchIdx >= 0) {
            setActiveIndex(matchIdx);
          }
        }
        break;
    }
  };

  return (
    <>
      {/* 1. Tombol Pemicu (Trigger Button) */}
      <button
        ref={triggerRef}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={listboxId}
        aria-label={ariaLabel || placeholder}
        onClick={handleToggle}
        onKeyDown={handleKeyDown}
        className={`custom-select-trigger ${isOpen ? "open" : ""} ${className}`}
      >
        {icon && <span className="custom-select-icon">{icon}</span>}
        <span className="custom-select-label" title={selectedOption?.label || placeholder}>
          {selectedOption ? selectedOption.label : placeholder}
        </span>
        <ChevronDown
          size={14}
          className={`custom-select-chevron ${isOpen ? "rotate-180" : ""}`}
        />
      </button>

      {/* 2. Panel Dropdown Desktop (Portal) atau Bottom Sheet Mobile (Portal) */}
      {mounted &&
        isOpen &&
        createPortal(
          isMobile ? (
            /* --- MODAL BOTTOM SHEET MOBILE (< 768px) --- */
            <div className="custom-select-backdrop" onClick={handleClose}>
              <div
                ref={panelRef}
                className="custom-select-bottom-sheet"
                onClick={(e) => e.stopPropagation()}
                role="dialog"
                aria-modal="true"
                aria-label={ariaLabel || placeholder}
                onKeyDown={handleKeyDown}
              >
                {/* Drag Handle & Header */}
                <div className="custom-select-sheet-header">
                  <div className="custom-select-drag-handle" />
                  <div className="custom-select-sheet-title-row">
                    <span className="custom-select-sheet-title">
                      {ariaLabel || placeholder}
                    </span>
                    <button
                      type="button"
                      onClick={handleClose}
                      className="custom-select-close-btn"
                      aria-label="Tutup"
                    >
                      <X size={18} />
                    </button>
                  </div>
                </div>

                {/* Kolom Pencarian Mobile */}
                {searchable && (
                  <div className="custom-select-search-box">
                    <Search size={14} className="custom-select-search-icon" />
                    <input
                      ref={searchInputRef}
                      type="text"
                      value={searchQuery}
                      onChange={(e) => {
                        setSearchQuery(e.target.value);
                        setActiveIndex(0);
                      }}
                      placeholder={searchPlaceholder}
                      className="custom-select-search-input"
                    />
                    {searchQuery && (
                      <button
                        type="button"
                        onClick={() => {
                          setSearchQuery("");
                          searchInputRef.current?.focus();
                        }}
                        className="custom-select-clear-search"
                        aria-label="Hapus teks cari"
                      >
                        <X size={13} />
                      </button>
                    )}
                  </div>
                )}

                {/* Daftar Opsi Mobile */}
                <div
                  ref={optionsListRef}
                  id={listboxId}
                  role="listbox"
                  className="custom-select-options-list custom-scrollbar"
                >
                  {filteredOptions.length === 0 ? (
                    <div className="custom-select-empty-state">
                      Tidak ada hasil yang cocok
                    </div>
                  ) : (
                    filteredOptions.map((opt, idx) => {
                      const isSelected = opt.value === value;
                      const isActive = idx === activeIndex;
                      const isFirstAfterAll = opt.isAll;

                      return (
                        <div
                          key={opt.value}
                          data-index={idx}
                          role="option"
                          aria-selected={isSelected}
                          onClick={() => handleSelect(opt.value)}
                          onMouseEnter={() => setActiveIndex(idx)}
                          className={`custom-select-option ${
                            isSelected ? "selected" : ""
                          } ${isActive ? "active" : ""} ${
                            isFirstAfterAll ? "option-divider-bottom" : ""
                          }`}
                        >
                          <span className="custom-select-opt-label">{opt.label}</span>
                          <div className="custom-select-opt-right">
                            {opt.count !== undefined && (
                              <span className="custom-select-opt-count">
                                ({opt.count})
                              </span>
                            )}
                            {isSelected && (
                              <Check size={16} strokeWidth={2.5} className="custom-select-check" />
                            )}
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </div>
          ) : (
            /* --- FLOATING POPOVER DESKTOP (>= 768px) --- */
            <div
              ref={panelRef}
              id={listboxId}
              role="listbox"
              aria-label={ariaLabel || placeholder}
              onKeyDown={handleKeyDown}
              className={`custom-select-popover ${
                popoverPos.openUpward ? "open-upward" : ""
              }`}
              style={{
                position: "fixed",
                top: popoverPos.openUpward ? undefined : `${popoverPos.top}px`,
                bottom: popoverPos.openUpward
                  ? `${window.innerHeight - popoverPos.top}px`
                  : undefined,
                left: `${popoverPos.left}px`,
                minWidth: `${popoverPos.width}px`,
                zIndex: 9999,
              }}
            >
              {/* Kolom Pencarian Desktop (Auto-focus) */}
              {searchable && (
                <div className="custom-select-search-box">
                  <Search size={13} className="custom-select-search-icon" />
                  <input
                    ref={searchInputRef}
                    type="text"
                    value={searchQuery}
                    onChange={(e) => {
                      setSearchQuery(e.target.value);
                      setActiveIndex(0);
                    }}
                    placeholder={searchPlaceholder}
                    className="custom-select-search-input"
                  />
                  {searchQuery && (
                    <button
                      type="button"
                      onClick={() => {
                        setSearchQuery("");
                        searchInputRef.current?.focus();
                      }}
                      className="custom-select-clear-search"
                      aria-label="Hapus teks cari"
                    >
                      <X size={12} />
                    </button>
                  )}
                </div>
              )}

              {/* Daftar Opsi Desktop */}
              <div
                ref={optionsListRef}
                className="custom-select-options-list custom-scrollbar"
              >
                {filteredOptions.length === 0 ? (
                  <div className="custom-select-empty-state">
                    Tidak ada hasil yang cocok
                  </div>
                ) : (
                  filteredOptions.map((opt, idx) => {
                    const isSelected = opt.value === value;
                    const isActive = idx === activeIndex;
                    const isFirstAfterAll = opt.isAll;

                    return (
                      <div
                        key={opt.value}
                        data-index={idx}
                        role="option"
                        aria-selected={isSelected}
                        onClick={() => handleSelect(opt.value)}
                        onMouseEnter={() => setActiveIndex(idx)}
                        className={`custom-select-option ${
                          isSelected ? "selected" : ""
                        } ${isActive ? "active" : ""} ${
                          isFirstAfterAll ? "option-divider-bottom" : ""
                        }`}
                      >
                        <span className="custom-select-opt-label">{opt.label}</span>
                        <div className="custom-select-opt-right">
                          {opt.count !== undefined && (
                            <span className="custom-select-opt-count">
                              ({opt.count})
                            </span>
                          )}
                          {isSelected && (
                            <Check size={14} strokeWidth={2.5} className="custom-select-check" />
                          )}
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          ),
          document.body
        )}
    </>
  );
}
