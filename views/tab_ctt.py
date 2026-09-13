import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


def render_tab_ctt(ctt_res, df_matrix=None, dfs=None):
    st.subheader("📈 Analisis Teori Tes Klasik (Classical Test Theory - CTT)")

    # --- NARASI TUJUAN & FUNGSI CTT ---
    with st.expander("📖 **Tujuan & Fungsi Analisis Teori Tes Klasik (CTT)**", expanded=False):
        st.markdown(
            """
            * **Tujuan Utama:** Menilai kualitas instrumen tes dan sebaran skor peserta secara menyeluruh berdasarkan sampel populasi yang ada.
            * **Fungsi Utama:**
              1. **Evaluasi Skor Murni Peserta:** Mengukur performa peserta berdasarkan proporsi jawaban benar (*skor mentah*).
              2. **Kualitas Butir Soal:** Menghitung **Tingkat Kesukaran ($p$)** dan **Daya Beda ($D/r$)** tiap soal untuk mengidentifikasi soal yang terlalu mudah, terlalu sulit, atau tidak valid.
              3. **Efektivitas Pengecoh (Distraktor):** Menganalisis apakah pilihan jawaban salah pada soal pilihan ganda berfungsi menarik perhatian peserta secara efektif.
              4. **Reliabilitas Tes:** Mengukur konsistensi dan keandalan perangkat tes secara keseluruhan (misal: Cronbach's Alpha).
            """
        )

    # Fallback jika ctt_res kosong tetapi ada di session state
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

    # --- FILTER MATA PELAJARAN / PAKET (JIKA ADA) ---
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

    # --- DETEKSI FLEKSIBEL NAMA KOLOM CTT ---
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

    # KONVERSI KOLOM DENGAN PAKSA KE FLOAT (Mencegah kegagalan kalkulasi saat dimuat dari MySQL)
    if p_col:
        df_items[p_col] = pd.to_numeric(df_items[p_col], errors="coerce")
    if d_col:
        df_items[d_col] = pd.to_numeric(df_items[d_col], errors="coerce")

    p_series = df_items[p_col] if p_col else pd.Series(dtype=float)
    d_series = df_items[d_col] if d_col else pd.Series(dtype=float)

    # --- RINGKASAN METRIK UTAMA (METRICS KPI) ---
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

    # =========================================================
    # TABEL STATISTIK DESKRIPTIF CTT
    # =========================================================
    st.markdown("### 📊 Statistik Deskriptif Analisis Klasik")

    col_desc1, col_desc2 = st.columns(2)

    with col_desc1:
        st.markdown("#### 1. Ringkasan Skor Mentah Peserta")
        
        # Fallback df_matrix jika None
        if df_matrix is None:
            df_matrix = st.session_state.get("df_matrix")

        skor_col = None
        if df_matrix is not None and not df_matrix.empty:
            skor_col = next(
                (
                    c
                    for c in df_matrix.columns
                    if c.lower()
                    in [
                        "skor_mentah",
                        "skor_konversi_ctt",
                        "skor",
                        "total_skor",
                        "nilai_konversi",
                    ]
                ),
                None,
            )

        if df_matrix is not None and skor_col is not None:
            scores = pd.to_numeric(df_matrix[skor_col], errors="coerce").dropna()
            
            if not scores.empty:
                score_stats = {
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
                        f"{len(scores):,}",
                        f"{scores.mean():.2f}",
                        f"{scores.std():.2f}" if len(scores) > 1 else "0.00",
                        f"{scores.min():.0f}",
                        f"{scores.quantile(0.25):.2f}",
                        f"{scores.median():.2f}",
                        f"{scores.quantile(0.75):.2f}",
                        f"{scores.max():.0f}",
                        f"{scores.skew():.3f}" if len(scores) > 2 else "0.000",
                        f"{scores.kurtosis():.3f}" if len(scores) > 3 else "0.000",
                    ],
                }
                st.dataframe(pd.DataFrame(score_stats), use_container_width=True, hide_index=True)
            else:
                st.info("Nilai numerik skor peserta tidak ditemukan.")
        else:
            st.info("Data skor peserta tidak ditemukan.")

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
                "Soal Daya Beda Buruk (D < 0.2)",
            ],
            "Nilai": [
                f"{len(df_items):,}",
                f"{p_vals.mean():.3f}" if not p_vals.empty else "-",
                f"{d_vals.mean():.3f}" if not d_vals.empty else "-",
                f"{(p_vals > 0.8).sum():,}" if not p_vals.empty else "-",
                f"{((p_vals >= 0.3) & (p_vals <= 0.8)).sum():,}" if not p_vals.empty else "-",
                f"{(p_vals < 0.3).sum():,}" if not p_vals.empty else "-",
                f"{(d_vals >= 0.3).sum():,}" if not d_vals.empty else "-",
                f"{(d_vals < 0.2).sum():,}" if not d_vals.empty else "-",
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
        st.caption(
            "🎯 **Tujuan:** Mengetahui proporsi sebaran soal berdasarkan tingkat kesulitannya (mudah, sedang, atau sulit)."
        )
        with st.expander("📖 Cara Membaca Grafik Kesukaran"):
            st.markdown(
                """
            * **Sumbu Horizontal (Nilai p):** Mengindikasikan proporsi peserta yang menjawab benar (skala 0,00 hingga 1,00).
            * **Nilai p > 0,70:** Soal tergolong **Mudah** (mayoritas peserta menjawab benar).
            * **Nilai 0,30 <= p <= 0,70:** Soal tergolong **Sedang / Ideal**.
            * **Nilai p < 0,30:** Soal tergolong **Sulit** (hanya sedikit peserta yang menjawab benar).
            """
            )

        if p_col:
            fig_p = px.histogram(
                df_items,
                x=p_col,
                nbins=15,
                title="<b>Sebaran Tingkat Kesukaran (p)</b>",
                labels={p_col: "Tingkat Kesukaran (p)"},
                color_discrete_sequence=["#636EFA"],
            )
            fig_p.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis_title="<b>Nilai p (Kesukaran)</b>",
                yaxis_title="<b>Jumlah Soal</b>",
            )
            st.plotly_chart(fig_p, use_container_width=True)

    with col_g2:
        st.markdown("#### Distribusi Daya Beda Soal (D)")
        st.caption(
            "🎯 **Tujuan:** Menilai seberapa baik butir-butir soal mampu membedakan peserta kelompok atas (pandai) dan bawah (kurang pandai)."
        )
        with st.expander("📖 Cara Membaca Grafik Daya Beda"):
            st.markdown(
                """
            * **Nilai D >= 0,40:** Soal **Sangat Baik** membedakan kemampuan peserta.
            * **Nilai 0,20 <= D < 0,40:** Soal **Cukup Baik** / perlu sedikit revisi.
            * **Nilai D < 0,20:** Soal **Daya Beda Rendah** (perlu direvisi atau dibuang).
            * **Nilai D Negatif (< 0):** **Anomali!** Peserta kelompok bawah justru lebih banyak menjawab benar dibanding kelompok atas.
            """
            )

        if d_col:
            fig_d = px.histogram(
                df_items,
                x=d_col,
                nbins=15,
                title="<b>Sebaran Daya Beda (D)</b>",
                labels={d_col: "Daya Beda (D)"},
                color_discrete_sequence=["#EF553B"],
            )
            fig_d.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis_title="<b>Nilai D (Daya Beda)</b>",
                yaxis_title="<b>Jumlah Soal</b>",
            )
            st.plotly_chart(fig_d, use_container_width=True)

    st.markdown("---")

    # =========================================================
    # 2. SCATTER PLOT & KUALITAS PROPORSI
    # =========================================================
    col_sc1, col_sc2 = st.columns([3, 2])

    with col_sc1:
        st.markdown("#### Matriks Hubungan Kesukaran vs Daya Beda")
        st.caption(
            "🎯 **Tujuan:** Memeta kuadran kualitas soal berdasarkan kombinasi tingkat kesukaran dan daya bedanya secara bersamaan."
        )
        with st.expander("📖 Cara Membaca Scatter Plot Kesukaran vs Daya Beda"):
            st.markdown(
                """
            * **Area Ideal (Tengah-Atas):** Soal berada pada rentang kesukaran sedang (0,30–0,70) dan daya beda tinggi (> 0,30).
            * **Area Bawah (Di bawah garis merah y=0,20):** Menandakan soal-soal bermasalah yang perlu ditinjau ulang atau diganti.
            """
            )

        if p_col and d_col:
            item_name_col = df_items.columns[0]
            fig_sc = px.scatter(
                df_items,
                x=p_col,
                y=d_col,
                hover_name=item_name_col,
                title="<b>Scatter Plot: Kesukaran (p) vs Daya Beda (D)</b>",
                labels={
                    p_col: "Tingkat Kesukaran (p)",
                    d_col: "Daya Beda (D)",
                },
                color_discrete_sequence=["#00CC96"],
            )
            fig_sc.add_hline(
                y=0.2,
                line_dash="dash",
                line_color="red",
                annotation_text="Batas Minimal D (0.20)",
            )
            fig_sc.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis_title="<b>Kesukaran (p)</b>",
                yaxis_title="<b>Daya Beda (D)</b>",
            )
            st.plotly_chart(fig_sc, use_container_width=True)

    with col_sc2:
        st.markdown("#### Proporsi Kualitas Butir Soal")
        st.caption(
            "🎯 **Tujuan:** Menampilkan persentase kesiapan seluruh perangkat soal berdasarkan rekomendasi analisis CTT."
        )
        with st.expander("📖 Cara Membaca Pie Chart Kualitas Soal"):
            st.markdown(
                """
            * **Diterima / Diterima Baik:** Soal berkualitas tinggi dan siap digunakan.
            * **Direvisi:** Soal memiliki sedikit kelemahan (misal: terlalu mudah/sulit atau pengecoh kurang berfungsi).
            * **Dibuang / Diganti:** Soal tidak efektif atau memiliki daya beda negatif/sangat rendah.
            """
            )

        rekom_cols = [
            c
            for c in df_items.columns
            if "rekomendasi" in c.lower() or "status" in c.lower()
        ]
        
        if rekom_cols:
            rekom_col = rekom_cols[0]
        else:
            rekom_col = "Rekomendasi"
            if d_col:
                df_items[rekom_col] = np.where(
                    d_series >= 0.30,
                    "Diterima Baik",
                    np.where(
                        d_series >= 0.20,
                        "Direvisi",
                        "Dibuang / Diganti",
                    ),
                )
            else:
                df_items[rekom_col] = "Belum Diketahui"

        counts = df_items[rekom_col].value_counts().reset_index()
        counts.columns = ["Kategori", "Jumlah"]

        color_map = {
            "Diterima Baik": "#00CC96",
            "Diterima": "#00CC96",
            "Direvisi": "#FECB52",
            "Dibuang / Diganti": "#EF553B",
            "Dibuang": "#EF553B",
        }

        fig_pie = px.pie(
            counts,
            names="Kategori",
            values="Jumlah",
            title="<b>Persentase Rekomendasi Soal</b>",
            hole=0.4,
            color="Kategori",
            color_discrete_map=color_map,
        )
        fig_pie.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    st.markdown("---")

    # =========================================================
    # 3. ANALISIS DISTRAKTOR / PENGECOH (JIKA TERSEDIA)
    # =========================================================
    df_dist = ctt_res.get("distractor_stats", pd.DataFrame())
    if isinstance(df_dist, pd.DataFrame) and not df_dist.empty:
        st.markdown("#### 🎯 Analisis Pengecoh (Distractor Analysis)")
        st.caption(
            "🎯 **Tujuan:** Memeriksa apakah opsi pilihan jawaban salah (pengecoh) berfungsi menarik minat peserta secara efektif."
        )
        with st.expander("📖 Cara Membaca Analisis Pengecoh & Grafik Opsi"):
            st.markdown(
                """
            * **Kunci Jawaban (Batang Hijau):** Harus dipilih oleh mayoritas peserta.
            * **Distraktor / Pengecoh (Batang Ungu):** Pilihan salah yang dianggap **efektif** jika dipilih oleh **minimal 5%** dari total peserta.
            * **Pengecoh Tidak Efektif:** Pilihan salah yang dipilih oleh **< 5%** peserta (opsi tersebut perlu diganti).
            """
            )

        item_code_col = next(
            (
                c
                for c in df_dist.columns
                if c.lower()
                in ["kode soal", "kode_soal", "item", "soal", "kode"]
            ),
            df_dist.columns[0],
        )
        items_list = sorted(df_dist[item_code_col].astype(str).unique().tolist())

        if items_list:
            selected_item = st.selectbox(
                "Pilih Soal untuk Dilihat Proporsi Pilihan Opsi Jawabannya:",
                options=items_list,
                key="select_distractor_item",
            )
            df_sub = df_dist[
                df_dist[item_code_col].astype(str) == selected_item
            ].copy()

            opsi_col = next(
                (
                    c
                    for c in df_sub.columns
                    if c.lower() in ["opsi", "option", "pilihan"]
                ),
                None,
            )
            pemilih_col = next(
                (
                    c
                    for c in df_sub.columns
                    if "jumlah" in c.lower()
                    or "pemilih" in c.lower()
                    or "count" in c.lower()
                    or "%" in c.lower()
                ),
                None,
            )
            kunci_col = next(
                (
                    c
                    for c in df_sub.columns
                    if "kunci" in c.lower() or "is_kunci" in c.lower()
                ),
                None,
            )

            if opsi_col and pemilih_col:
                fig_opsi = px.bar(
                    df_sub,
                    x=opsi_col,
                    y=pemilih_col,
                    color=kunci_col if kunci_col else None,
                    title=f"<b>Sebaran Pemilihan Opsi Jawaban - Soal {selected_item}</b>",
                    color_discrete_map={True: "#00CC96", False: "#AB63FA"},
                    labels={
                        opsi_col: "Opsi Jawaban",
                        pemilih_col: "Jumlah Pemilih",
                        kunci_col: "Kunci Jawaban",
                    },
                )
                fig_opsi.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_opsi, use_container_width=True)

        with st.expander("📋 Lihat Tabel Detail Analisis Pengecoh Lengkap"):
            st.dataframe(df_dist, use_container_width=True, hide_index=True)

        st.markdown("---")

    # =========================================================
    # 4. TABEL DETAIL STATISTIK BUTIR SOAL
    # =========================================================
    st.markdown("#### 📋 Tabel Detail Statistik Butir Soal (CTT)")
    st.caption(
        "🎯 **Tujuan:** Menampilkan tabel parameter lengkap CTT untuk setiap butir soal sebagai acuan evaluasi tim penyusun soal."
    )
    with st.expander("📖 Cara Membaca & Memanfaatkan Tabel CTT"):
        st.markdown(
            """
        * Urutkan kolom **Daya Beda (D)** dari yang terkecil untuk menemukan soal-soal bermasalah yang harus diperbaiki terlebih dahulu.
        * Kolom **Rekomendasi** memuat status otomatis apakah butir soal siap digunakan, perlu diperbaiki, atau diganti.
        """
        )

    df_display = df_items.copy()
    if "No." not in df_display.columns:
        df_display.insert(0, "No.", range(1, 1 + len(df_display)))

    st.dataframe(df_display, use_container_width=True, hide_index=True)