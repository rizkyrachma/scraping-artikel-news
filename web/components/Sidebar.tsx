"use client";

import React from "react";
import { LayoutDashboard, Download, History, Newspaper } from "lucide-react";

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  reviewCount?: number;
}

export default function Sidebar({ activeTab, setActiveTab }: SidebarProps) {
  const navItems = [
    { id: "overview", label: "Overview", icon: LayoutDashboard },
    { id: "unduh", label: "Unduh Data", icon: Download },
    { id: "riwayat", label: "Riwayat Run", icon: History },
    { id: "berita", label: "Berita", icon: Newspaper },
  ];

  return (
    <aside className="sidebar-container panel-primary">
      <div className="sidebar-top">
        <div className="sidebar-brand">
          <div className="brand-title">
            <span className="brand-text">Media Monitoring</span>
            <span className="brand-dot">.</span>
          </div>
          <div className="brand-subtitle">Ditjen Industri Agro</div>
        </div>

        <nav className="sidebar-nav">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setActiveTab(item.id)}
                className={`sidebar-nav-btn ${isActive ? "active" : ""}`}
                title={item.label}
              >
                <Icon size={18} strokeWidth={2} className="nav-icon" />
                <span className="nav-label">{item.label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      <div className="sidebar-footer">
        <span className="footer-full">Ditjen Industri Agro • v1.0</span>
        <span className="footer-mini">v1.0</span>
      </div>
    </aside>
  );
}
