"use client";

import React from "react";
import { LayoutDashboard, Download, History, Newspaper } from "lucide-react";

interface BottomNavProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
}

export default function BottomNav({ activeTab, setActiveTab }: BottomNavProps) {
  const navItems = [
    { id: "overview", label: "Overview", icon: LayoutDashboard },
    { id: "unduh", label: "Unduh Data", icon: Download },
    { id: "riwayat", label: "Riwayat Run", icon: History },
    { id: "berita", label: "Berita", icon: Newspaper },
  ];

  return (
    <nav className="mobile-bottom-nav">
      {navItems.map((item) => {
        const Icon = item.icon;
        const isActive = activeTab === item.id;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => setActiveTab(item.id)}
            className={`bottom-nav-item ${isActive ? "active" : ""}`}
          >
            <Icon size={20} strokeWidth={isActive ? 2.5 : 2} />
            <span className="bottom-nav-label">{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
