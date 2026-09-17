import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


def render_tab_ctt(ctt_res, df_matrix=None, dfs=None):
    st.subheader("📈 Analisis Teori Tes Klasik (Classical Test Theory - CTT)")

    with st.expander("📖 **Tujuan & Fungsi Analisis Teori Tes Klasik (CTT)**", expanded=False):
        st.markdown(
            """
            * **Tujuan Utama:** Menilai kualitas instrumen tes dan sebaran skor peserta secara menyeluruh berdasarkan sampel populasi yang ada.
            * **Fungsi Utama:**
              1. **Evaluasi Nilai Konversi Peserta:** Mengukur performa peserta berdasarkan nilai konversi skala standar.
              2. **Kualitas Butir Soal:** Menghitung **Tingkat Kesukaran ($p$)** dan **Daya Beda ($D/r$)** tiap soal untuk mengidentifikasi soal yang terlalu mudah, terlalu sulit, atau tidak valid.
              3. **Efektivitas Pengecoh (Distraktor):** Menganalisis apakah pilihan jawaban salah pada soal pilihan ganda berfungsi menarik perhatian peserta secara efektif.
              4. **Reliabilitas Tes:** Mengukur konsistensi dan keandalan perangkat tes secara keseluruhan (misal: Cronbach's Alpha).
            """
        )

    if ctt_res is None or not isinstance(ctt_res, dict):
        ctt_res = st.session_state.get("ctt_res", {})

    if not ctt_res or "item_stats" not in ctt_res or ctt_res["item_stats"] is None:
        st.warning(
            "⚠️ Data analisis CTT belum tersedia. Silakan unggah atau jalankan proses data terlebih dahulu."
        )
        return

    df_items = ctt_res["item_stats"].copy()

    if df_items.empty:
        st.warning("⚠️ Tabel item_stats kosong.")
        return

    mapel_cols = [
        c
        for c in df_items.columns
        if c.lower()
        in ["mapel", "mata_pelajaran", "mata pelajaran", "subject", "paket"]
    ]
    if mapel_cols:
        mapel_col = mapel_cols[0]
        list_mapel = ["Semua"] + sorted(
            df_items[mapel_col].dropna().unique().tolist()
        )
        selected_mapel = st.selectbox(
            "Filter Mata Pelajaran / Paket:", options=list_mapel, key="filter_ctt_mapel"
        )
        if selected_mapel != "Semua":
            df_items = df_items[df_items[mapel_col] == selected_mapel].copy()

    p_col = next(
        (
            c
            for c in df_items.columns
            if c.lower().strip() in [
                "tingkat_kesukaran_ctt",
                "tingkat kesukaran",
                "kesukaran",
                "p_value",
                "p",
                "mean",
            ]
            or "kesukaran" in c.lower()
        ),
        None,
    )
    d_col = next(
        (
            c
            for c in df_items.columns
            if c.lower().strip() in [
                "daya_beda_ctt",
                "daya_beda",
                "daya beda",
                "daya_beda_r",
                "d",
                "rit",
                "rir",
            ]
            or "daya_beda" in c.lower()
            or "daya beda" in c.lower()
        ),
        None,
    )

    if p_col:
        df_items[p_col] = pd.to_numeric(df_items[p_col], errors="coerce")
    if d_col:
        df_items[d_col] = pd.to_numeric(df_items[d_col], errors="coerce")

    p_series = df_items[p_col] if p_col else pd.Series(dtype=float)
    d_series = df_items[d_col] if d_col else pd.Series(dtype=float)

    st.markdown("#### 📌 Ringkasan Parameter Klasik (CTT)")

    col1, col2, col3, col4 = st.columns(4)

    total_items = len(df_items)
    mean_p = p_series.dropna().mean() if not p_series.dropna().empty else 0.0
    mean_d = d_series.dropna().mean() if not d_series.dropna().empty else 0.0
    rel_val = ctt_res.get(
        "Reliabilitas",
        ctt_res.get("cronbach_alpha", ctt_res.get("reliability", 0.53)),
    )

    col1.metric("Total Soal Teranalisis", f"{total_items} Butir")
    col2.metric(
        "Rata-rata Kesukaran (p)",
        f"{mean_p:.2f}" if pd.notna(mean_p) else "0.00",
        help="Skala 0 - 1. Semakin mendekati 1 semakin mudah.",
    )
    col3.metric(
        "Rata-rata Daya Beda (D)",
        f"{mean_d:.2f}" if pd.notna(mean_d) else "0.00",
        help="Semakin tinggi semakin baik membedakan siswa pandai/lemah.",
    )
    col4.metric(
        "Reliabilitas (Alpha)",
        f"{float(rel_val):.2f}" if pd.notna(rel_val) else "0.00",
        help="Akurasi konsistensi tes (> 0.70 tergolong baik).",
    )

    st.markdown("---")
    st.markdown("### 📊 Statistik Deskriptif Analisis Klasik")

    if df_matrix is None:
        df_matrix = st.session_state.get("df_matrix")

    konversi_col = None
    if df_matrix is not None and not df_matrix.empty:
        konversi_col = next(
            (
                c
                for c in df_matrix.columns
                if c.lower()
                in [
                    "skor_konversi",
                    "nilai_konversi",
                    "skor_konversi_ctt",
                    "skor_konversi_irt",
                    "konversi",
                ]
                or "konversi" in c.lower()
            ),
            None,
        )

    col_desc1, col_desc2 = st.columns(2)

    with col_desc1:
        st.markdown("#### 1. Ringkasan Nilai Konversi Peserta")
        if df_matrix is not None and konversi_col is not None:
            conv_scores = pd.to_numeric(df_matrix[konversi_col], errors="coerce").dropna()
            if not conv_scores.empty:
                q1_val = conv_scores.quantile(0.25)
                med_val = conv_scores.median()
                q3_val = conv_scores.quantile(0.75)
                skew_val = conv_scores.skew() if len(conv_scores) > 2 else 0.0
                kurt_val = conv_scores.kurtosis() if len(conv_scores) > 3 else 0.0

                conv_stats = {
                    "Metrik Statistik": [
                        "Jumlah Peserta (N)",
                        "Rata-rata Skor (Mean)",
                        "Standar Deviasi (SD)",
                        "Skor Minimum",
                        "Kuartil 1 (Q1 - 25%)",
                        "Median (Q2 - 50%)",
                        "Kuartil 3 (Q3 - 75%)",
                        "Skor Maksimum",
                        "Kemiringan (Skewness)",
                        "Keruncingan (Kurtosis)",
                    ],
                    "Nilai": [
                        f"{len(conv_scores):,}",
                        f"{conv_scores.mean():.2f}",
                        f"{conv_scores.std():.2f}" if len(conv_scores) > 1 else "0.00",
                        f"{conv_scores.min():.2f}",
                        f"{q1_val:.2f}",
                        f"{med_val:.2f}",
                        f"{q3_val:.2f}",
                        f"{conv_scores.max():.2f}",
                        f"{skew_val:.3f}",
                        f"{kurt_val:.3f}",
                    ],
                }
                st.dataframe(pd.DataFrame(conv_stats), use_container_width=True, hide_index=True)
            else:
                st.info("Data nilai konversi kosong.")
        else:
            st.info("Kolom nilai konversi belum ditemukan / digenerate.")

    with col_desc2:
        st.markdown("#### 2. Ringkasan Parameter Butir Soal (CTT)")
        p_vals = p_series.dropna()
        d_vals = d_series.dropna()
        item_summary = {
            "Metrik Parameter": [
                "Jumlah Soal (N)",
                "Rata-rata Tingkat Kesukaran (Mean p)",
                "Rata-rata Daya Beda (Mean D)",
                "Soal Sangat Mudah (p > 0.8)",
                "Soal Sedang (0.3 <= p <= 0.8)",
                "Soal Sangat Sulit (p < 0.3)",
                "Soal Daya Beda Baik (D >= 0.3)",
                "Soal Daya Beda Buruk (D < 0.3)",
            ],
            "Nilai": [
                f"{len(df_items):,}",
                f"{p_vals.mean():.3f}" if not p_vals.empty else "-",
                f"{d_vals.mean():.3f}" if not d_vals.empty else "-",
                f"{(p_vals > 0.8).sum():,}" if not p_vals.empty else "-",
                f"{((p_vals >= 0.3) & (p_vals <= 0.8)).sum():,}" if not p_vals.empty else "-",
                f"{(p_vals < 0.3).sum():,}" if not p_vals.empty else "-",
                f"{(d_vals >= 0.3).sum():,}" if not d_vals.empty else "-",
                f"{(d_vals < 0.3).sum():,}" if not d_vals.empty else "-",
            ],
        }
        st.dataframe(pd.DataFrame(item_summary), use_container_width=True, hide_index=True)

    st.markdown("---")

    # =========================================================
    # 1. GRAFIK DISTRIBUSI KESUKARAN DAN DAYA BEDA
    # =========================================================
    col_g1, col_g2 = st.columns(2)

    with col_g1:
        st.markdown("#### Distribusi Tingkat Kesukaran Soal (p)")
        st.caption("🎯 **Tujuan:** Mengetahui proporsi sebaran soal berdasarkan tingkat kesulitannya.")
        with st.expander("📖 Cara Membaca Grafik Kesukaran"):
            st.markdown(
                """
            * **Nilai p > 0,70:** Soal tergolong **Mudah**.
            * **Nilai 0,30 <= p <= 0,70:** Soal tergolong **Sedang / Ideal**.
            * **Nilai p < 0,30:** Soal tergolong **Sulit**.
            """
            )

        if p_col:
            fig_p = px.histogram(
                df_items, x=p_col, nbins=15, title="<b>Sebaran Tingkat Kesukaran (p)</b>",
                labels={p_col: "Tingkat Kesukaran (p)"}, color_discrete_sequence=["#636EFA"]
            )
            fig_p.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_p, use_container_width=True)

    with col_g2:
        st.markdown("#### Distribusi Daya Beda Soal (D)")
        st.caption("🎯 **Tujuan:** Menilai kemampuan butir soal membedakan kelompok atas/bawah.")
        with st.expander("📖 Cara Membaca Grafik Daya Beda"):
            st.markdown(
                """
            * **Nilai D >= 0,40:** **Sangat Baik**.
            * **Nilai 0,20 <= D < 0,40:** **Cukup Baik**.
            * **Nilai D < 0,20:** **Rendah** (perlu revisi).
            * **Nilai D Negatif (< 0):** **Anomali**.
            """
            )

        if d_col:
            fig_d = px.histogram(
                df_items, x=d_col, nbins=15, title="<b>Sebaran Daya Beda (D)</b>",
                labels={d_col: "Daya Beda (D)"}, color_discrete_sequence=["#EF553B"]
            )
            fig_d.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_d, use_container_width=True)

    st.markdown("---")

    # =========================================================
    # 2. SCATTER PLOT & KUALITAS PROPORSI
    # =========================================================
    col_sc1, col_sc2 = st.columns(2)

    with col_sc1:
        st.markdown("#### Matriks Hubungan Kesukaran vs Daya Beda")
        if p_col and d_col:
            item_name_col = df_items.columns[0]
            fig_sc = px.scatter(
                df_items, x=p_col, y=d_col, hover_name=item_name_col,
                title="<b>Scatter Plot: Kesukaran (p) vs Daya Beda (D)</b>",
                labels={p_col: "Tingkat Kesukaran (p)", d_col: "Daya Beda (D)"},
                color_discrete_sequence=["#00CC96"]
            )
            fig_sc.add_hline(y=0.2, line_dash="dash", line_color="red", annotation_text="Batas Minimal D (0.20)")
            fig_sc.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_sc, use_container_width=True)

    with col_sc2:
        st.markdown("#### Proporsi Kualitas Butir Soal")
        rekom_cols = [c for c in df_items.columns if "rekomendasi" in c.lower() or "status" in c.lower()]
        rekom_col = rekom_cols[0] if rekom_cols else "Rekomendasi"
        if not rekom_cols and d_col:
            df_items[rekom_col] = np.where(d_series >= 0.30, "Diterima Baik", np.where(d_series >= 0.20, "Direvisi", "Dibuang / Diganti"))
        elif not rekom_cols:
            df_items[rekom_col] = "Belum Diketahui"

        counts = df_items[rekom_col].value_counts().reset_index()
        counts.columns = ["Kategori", "Jumlah"]
        color_map = {"Diterima Baik": "#00CC96", "Diterima": "#00CC96", "Direvisi": "#FECB52", "Dibuang / Diganti": "#EF553B", "Dibuang": "#EF553B"}
        fig_pie = px.pie(counts, names="Kategori", values="Jumlah", title="<b>Persentase Rekomendasi Soal</b>", hole=0.4, color="Kategori", color_discrete_map=color_map)
        fig_pie.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_pie, use_container_width=True)

    st.markdown("---")

    # =========================================================
    # 3. TABEL DETAIL STATISTIK BUTIR SOAL
    # =========================================================
    st.markdown("#### 📋 Tabel Detail Statistik Butir Soal (CTT)")
    df_display = df_items.copy()
    if "No." not in df_display.columns:
        df_display.insert(0, "No.", range(1, 1 + len(df_display)))
    st.dataframe(df_display, use_container_width=True, hide_index=True)