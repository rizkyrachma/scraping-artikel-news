"use client";

import React from "react";

interface PageHeaderCardProps {
  title: string;
  description: React.ReactNode;
}

export default function PageHeaderCard({ title, description }: PageHeaderCardProps) {
  return (
    <div className="tab-header-card">
      <h1 className="tab-page-title tab-page-title-accented">{title}</h1>
      <p className="tab-page-desc">{description}</p>
    </div>
  );
}
