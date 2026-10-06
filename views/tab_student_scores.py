# views/tab_student_scores.py
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from db_helper import get_db_connection
from excel_exporter import convert_df_to_csv_bytes, convert_df_to_excel_bytes
from validators import get_mapel_lookup_dict


@st.cache_data(ttl=60)
def load_data_from_mysql():
    """Membaca seluruh data peserta dan skor langsung dari MySQL Server."""
    try:
        engine = get_db_connection()
        if engine is None:
            return None
        query = "SELECT * FROM tb_peserta_skor"
        df = pd.read_sql_query(query, con=engine)
        return df
    except Exception:
        return None


@st.cache_data(ttl=60)
def load_biodata_from_mysql():
    """Membaca tabel master biodata dari MySQL Server untuk enrichment jika diperlukan."""
    try:
        engine = get_db_connection()
        if engine is None:
            return None
        df_bio = pd.read_sql_query("SELECT * FROM tb_master_biodata", con=engine)
        return df_bio
    except Exception:
        return None


def enrich_biodata_if_needed(df_target: pd.DataFrame, dfs=None) -> pd.DataFrame:
    """Memastikan kolom username, nisn, nama, jenis_kelamin terisi lengkap dari dfs atau tb_master_biodata."""
    if df_target is None or df_target.empty:
        return df_target

    df_out = df_target.copy()

    # Normalisasi nama kolom user
    if "username" not in df_out.columns:
        for c in ["Username", "user_id", "id_peserta", "idpeserta", "id"]:
            if c in df_out.columns:
                df_out["username"] = df_out[c]
                break
        if "username" not in df_out.columns:
            df_out["username"] = df_out.iloc[:, 0]

    df_out["username"] = df_out["username"].astype(str).str.strip()

    # Periksa apakah nisn, nama, jenis_kelamin sudah ada dan valid
    needs_nisn = "nisn" not in df_out.columns or df_out["nisn"].isna().all() or (df_out["nisn"] == "-").all()
    needs_nama = "nama" not in df_out.columns or df_out["nama"].isna().all() or (df_out["nama"] == "-").all()
    needs_jk = "jenis_kelamin" not in df_out.columns or df_out["jenis_kelamin"].isna().all() or (df_out["jenis_kelamin"] == "-").all()

    if not (needs_nisn or needs_nama or needs_jk):
        return df_out

    # Coba ambil dari dfs['biodata'] terlebih dahulu
    df_bio = None
    if dfs and isinstance(dfs, dict) and "biodata" in dfs and dfs["biodata"] is not None and not dfs["biodata"].empty:
        df_bio = dfs["biodata"].copy()
    else:
        # Fallback ke tb_master_biodata di MySQL
        df_bio = load_biodata_from_mysql()

    if df_bio is not None and not df_bio.empty:
        df_bio_clean = df_bio.copy()
        df_bio_clean.columns = [str(c).strip().lower() for c in df_bio_clean.columns]

        col_u = next(
            (c for c in df_bio_clean.columns if str(c) in ["username", "user_id", "id_peserta", "idpeserta", "id"]),
            df_bio_clean.columns[0]
        )
        col_nisn = next((c for c in df_bio_clean.columns if "nisn" in c), None)
        col_nama = next(
            (c for c in df_bio_clean.columns if "nama" in c and "sekolah" not in c and "kabupaten" not in c and "provinsi" not in c),
            None
        )
        col_jk = next(
            (c for c in df_bio_clean.columns if any(kw in c for kw in ["jenis_kelamin", "jeniskelamin", "jk", "gender", "sex", "kelamin", "l/p", "lp"])),
            None
        )

        df_bio_clean["_u_key"] = df_bio_clean[col_u].astype(str).str.strip().str.lower()
        bio_map_nisn = dict(zip(df_bio_clean["_u_key"], df_bio_clean[col_nisn].astype(str).str.strip())) if col_nisn else {}
        bio_map_nama = dict(zip(df_bio_clean["_u_key"], df_bio_clean[col_nama].astype(str).str.strip())) if col_nama else {}
        bio_map_jk = dict(zip(df_bio_clean["_u_key"], df_bio_clean[col_jk].astype(str).str.strip())) if col_jk else {}

        target_u_keys = df_out["username"].astype(str).str.strip().str.lower()

        if needs_nisn and bio_map_nisn:
            df_out["nisn"] = target_u_keys.map(bio_map_nisn).fillna("-")
        elif "nisn" not in df_out.columns:
            df_out["nisn"] = "-"

        if needs_nama and bio_map_nama:
            df_out["nama"] = target_u_keys.map(bio_map_nama).fillna(df_out["username"])
        elif "nama" not in df_out.columns:
            df_out["nama"] = df_out["username"]

        if needs_jk and bio_map_jk:
            df_out["jenis_kelamin"] = target_u_keys.map(bio_map_jk).fillna("-")
        elif "jenis_kelamin" not in df_out.columns:
            df_out["jenis_kelamin"] = "-"
    else:
        if "nisn" not in df_out.columns:
            df_out["nisn"] = "-"
        if "nama" not in df_out.columns:
            df_out["nama"] = df_out["username"]
        if "jenis_kelamin" not in df_out.columns:
            df_out["jenis_kelamin"] = "-"

    # Rapikan nilai kosong
    df_out["nisn"] = df_out["nisn"].replace(["nan", "None", "NONE", ""], "-").fillna("-")
    df_out["nama"] = df_out["nama"].replace(["nan", "None", "NONE", ""], "-").fillna("-")
    df_out["jenis_kelamin"] = df_out["jenis_kelamin"].replace(["nan", "None", "NONE", ""], "-").fillna("-")

    return df_out


def render_tab_student_scores(df_matrix_school, dfs=None):
    """Menampilkan Tab 7: Rekap Nilai Siswa Per Mata Pelajaran dan Statistik Deskriptif Sekolah."""
    st.subheader("👨‍🎓 Rekap Nilai Siswa Per Mata Pelajaran")
    st.markdown(
        "<p style='color: #64748B; font-size: 0.95rem; margin-top: -6px;'>"
        "Pilih sekolah melalui filter bertingkat <b>Provinsi &rarr; Kabupaten/Kota/Rayon &rarr; Sekolah</b> "
        "untuk melihat perolehan nilai siswa per mata pelajaran serta statistik deskriptif sekolah."
        "</p>",
        unsafe_allow_html=True,
    )

    # --- 1. AMBIL DATA MASTER (MEMORY -> FALLBACK MYSQL) ---
    cand_df = st.session_state.get("df_peserta_skor")
    if cand_df is None or cand_df.empty:
        cand_df = df_matrix_school if (df_matrix_school is not None and not df_matrix_school.empty) else None

    if cand_df is None or cand_df.empty:
        df_db = load_data_from_mysql()
        if df_db is not None and not df_db.empty:
            cand_df = df_db
            st.session_state["df_peserta_skor"] = cand_df
        else:
            st.info(
                "💡 **Informasi:** Data peserta atau skor belum tersedia. "
                "Silakan unggah berkas dan lakukan proses data terlebih dahulu pada tab sebelumnya."
            )
            return

    # Normalisasi lookup nama mata pelajaran
    mapel_lookup = {}
    if dfs and isinstance(dfs, dict) and "mapel" in dfs and dfs["mapel"] is not None and not dfs["mapel"].empty:
        mapel_lookup = get_mapel_lookup_dict(dfs["mapel"])
    if not mapel_lookup:
        mapel_lookup = st.session_state.get("mapel_dict", {})
    if not mapel_lookup:
        mapel_lookup = get_mapel_lookup_dict(None)

    # --- 2. PILIHAN METRIK SKOR / NILAI ---
    score_metric_options = {}
    if "skor_konversi_ctt" in cand_df.columns:
        score_metric_options["Nilai Skala CTT (0 - 100)"] = "skor_konversi_ctt"
    if "skor_mentah" in cand_df.columns:
        score_metric_options["Skor Mentah (Jumlah Benar)"] = "skor_mentah"
    if "skor_konversi_rasch" in cand_df.columns:
        score_metric_options["Nilai Skala IRT Rasch"] = "skor_konversi_rasch"
    if "skor_konversi_1pl" in cand_df.columns:
        score_metric_options["Nilai Skala IRT 1-PL"] = "skor_konversi_1pl"
    if "skor_konversi_2pl" in cand_df.columns:
        score_metric_options["Nilai Skala IRT 2-PL"] = "skor_konversi_2pl"
    if "skor_konversi_3pl" in cand_df.columns:
        score_metric_options["Nilai Skala IRT 3-PL"] = "skor_konversi_3pl"

    if not score_metric_options:
        score_metric_options["Nilai"] = "skor_mentah" if "skor_mentah" in cand_df.columns else cand_df.columns[-1]

    # --- 3. FILTER BERTINGKAT (PROVINSI -> KABUPATEN/KOTA -> SEKOLAH) DENGAN CACHE RINGAN ---
    st.markdown("#### 🎯 Filter Wilayah & Satuan Pendidikan")

    col_flt_prov, col_flt_kab, col_flt_sek = st.columns(3)

    # Ambil hierarki wilayah ringan (hanya 36k baris unik, bukan 3.34 juta baris)
    df_geo = st.session_state.get("geo_hierarchy")
    if df_geo is None or df_geo.empty:
        df_comp = st.session_state.get("df_school_composite")
        if df_comp is not None and not df_comp.empty and "nama_provinsi" in df_comp.columns:
            df_geo = df_comp[["kode_provinsi", "nama_provinsi", "nama_kabupaten", "kode_sekolah", "nama_sekolah"]].drop_duplicates()
        else:
            from analytics_cache import compute_geo_hierarchy
            df_geo = compute_geo_hierarchy(cand_df)
            st.session_state["geo_hierarchy"] = df_geo

    # 1. Pilihan Provinsi
    prov_list = sorted([
        str(p).strip() for p in df_geo["nama_provinsi"].dropna().unique()
        if str(p).strip() not in ["", "nan", "None", "-", "TIDAK TERDEFINISI"]
    ])
    if not prov_list:
        prov_list = ["Semua Provinsi"]

    with col_flt_prov:
        selected_prov = st.selectbox(
            "1️⃣ Provinsi:",
            options=prov_list,
            index=0,
            key="tab7_sel_prov",
            help="Pilih provinsi satuan pendidikan",
        )

    # Filter hierarki berdasarkan provinsi
    df_geo_prov = df_geo[df_geo["nama_provinsi"] == selected_prov] if selected_prov in prov_list else df_geo

    # 2. Pilihan Kabupaten/Kota/Rayon
    kab_list = sorted([
        str(k).strip() for k in df_geo_prov["nama_kabupaten"].dropna().unique()
        if str(k).strip() not in ["", "nan", "None", "-", "TIDAK TERDEFINISI"]
    ])
    if not kab_list:
        kab_list = ["Semua Kabupaten/Kota"]

    with col_flt_kab:
        selected_kab = st.selectbox(
            "2️⃣ Kabupaten / Kota / Rayon:",
            options=kab_list,
            index=0,
            key="tab7_sel_kab",
            help="Pilih kabupaten atau kota pada provinsi terpilih",
        )

    df_geo_kab = df_geo_prov[df_geo_prov["nama_kabupaten"] == selected_kab] if selected_kab in kab_list else df_geo_prov

    # 3. Pilihan Sekolah
    df_sch_unique = df_geo_kab[["kode_sekolah", "nama_sekolah"]].drop_duplicates().sort_values(by="nama_sekolah")
    sch_options = []
    sch_lookup = {}
    for _, row in df_sch_unique.iterrows():
        kd = str(row["kode_sekolah"]).strip()
        nm = str(row["nama_sekolah"]).strip()
        label = f"{nm} ({kd})" if kd not in ["-", "", "nan"] and kd != nm else nm
        sch_options.append(label)
        sch_lookup[label] = (kd, nm)

    if not sch_options:
        st.warning("⚠️ Tidak ada data sekolah yang ditemukan pada wilayah yang dipilih.")
        return

    with col_flt_sek:
        selected_sch_label = st.selectbox(
            "3️⃣ Sekolah:",
            options=sch_options,
            index=0,
            key="tab7_sel_sch",
            help="Pilih sekolah untuk melihat data nilai siswa dan statistik deskriptif",
        )

    target_kd, target_nm = sch_lookup[selected_sch_label]

    # Filter data KHUSUS sekolah terpilih secara instan (hanya menghasilkan ~20-100 baris, bukan 3.34 juta baris)
    sek_col = "kode_sekolah" if "kode_sekolah" in cand_df.columns else "_school_key" if "_school_key" in cand_df.columns else None
    if sek_col and target_kd not in ["-", "", "nan"]:
        df_school = cand_df[cand_df[sek_col].astype(str).str.strip() == target_kd].copy()
    elif "nama_sekolah" in cand_df.columns and target_nm not in ["-", "", "nan"]:
        df_school = cand_df[cand_df["nama_sekolah"].astype(str).str.strip() == target_nm].copy()
    else:
        u_col = "username" if "username" in cand_df.columns else cand_df.columns[0]
        df_school = cand_df[cand_df[u_col].astype(str).str[:9].str.upper() == target_kd].copy()

    if df_school.empty:
        st.info("ℹ️ Tidak ada data peserta untuk sekolah terpilih.")
        return

    # Normalisasi kolom identitas sekolah pada subset terpilih
    if "kode_sekolah" not in df_school.columns:
        df_school["kode_sekolah"] = target_kd
    if "nama_sekolah" not in df_school.columns:
        df_school["nama_sekolah"] = target_nm
    if "nama_kabupaten" not in df_school.columns:
        df_school["nama_kabupaten"] = selected_kab
    if "nama_provinsi" not in df_school.columns:
        df_school["nama_provinsi"] = selected_prov

    if "mapel" in df_school.columns and mapel_lookup:
        df_school["mapel"] = df_school["mapel"].map(
            lambda x: mapel_lookup.get(str(x).strip().upper(), mapel_lookup.get(str(x).strip(), str(x).strip()))
        )

    # Lengkapi biodata siswa (NISN, Nama, Gender) HANYA untuk siswa di sekolah ini saja
    df_school = enrich_biodata_if_needed(df_school, dfs)

    # Opsi pilihan metrik nilai di bagian samping filter atau accordion
    col_metric, col_dummy = st.columns([2.5, 3.5])
    with col_metric:
        selected_metric_label = st.selectbox(
            "📊 Jenis Nilai yang Ditampilkan:",
            options=list(score_metric_options.keys()),
            index=0,
            key="tab7_sel_metric",
            help="Pilih skala nilai yang ingin ditampilkan di tabel rekap siswa dan statistik",
        )
    metric_col = score_metric_options[selected_metric_label]

    st.markdown("---")

    # --- 4. STATISTIK DESKRIPTIF SEKOLAH ---
    st.markdown(f"### 🏫 Statistik Deskriptif: {target_nm}")
    if target_kd != "-" and target_kd != target_nm:
        st.caption(f"NPSN / Kode Sekolah: `{target_kd}` | Wilayah: **{selected_kab}, {selected_prov}**")

    # Pastikan kolom metrik berupa numerik
    df_school[metric_col] = pd.to_numeric(df_school[metric_col], errors="coerce")

    # Hitung ringkasan per mapel untuk sekolah ini
    mapels_in_school = sorted([
        str(m).strip() for m in df_school["mapel"].dropna().unique()
        if str(m).strip() not in ["", "nan", "None", "-"]
    ])

    stat_rows = []
    for m in mapels_in_school:
        sub_df = df_school[df_school["mapel"] == m][metric_col].dropna()
        if not sub_df.empty:
            stat_rows.append({
                "Mata Pelajaran": m,
                "Jumlah Siswa (N)": int(len(sub_df)),
                "Rata-rata (Mean)": round(float(sub_df.mean()), 2),
                "Median": round(float(sub_df.median()), 2),
                "Standar Deviasi (SD)": round(float(sub_df.std()), 2) if len(sub_df) > 1 else 0.0,
                "Nilai Min": round(float(sub_df.min()), 2),
                "Nilai Max": round(float(sub_df.max()), 2),
                "Rentang (Range)": round(float(sub_df.max() - sub_df.min()), 2),
            })
        else:
            stat_rows.append({
                "Mata Pelajaran": m,
                "Jumlah Siswa (N)": 0,
                "Rata-rata (Mean)": 0.0,
                "Median": 0.0,
                "Standar Deviasi (SD)": 0.0,
                "Nilai Min": 0.0,
                "Nilai Max": 0.0,
                "Rentang (Range)": 0.0,
            })

    df_stat = pd.DataFrame(stat_rows)

    # KPI Summary Cards Sekolah
    total_siswa_sekolah = df_school["username"].nunique()
    total_mapel_sekolah = len(mapels_in_school)
    rata_total_sekolah = df_school[metric_col].mean() if not df_school[metric_col].dropna().empty else 0.0
    sd_total_sekolah = df_school[metric_col].std() if len(df_school[metric_col].dropna()) > 1 else 0.0

    kpi_c1, kpi_c2, kpi_c3, kpi_c4 = st.columns(4)
    kpi_c1.metric("👥 Total Siswa", f"{total_siswa_sekolah:,} orang")
    kpi_c2.metric("📚 Jumlah Mata Pelajaran", f"{total_mapel_sekolah} Mapel")
    kpi_c3.metric(f"📈 Rata-rata ({selected_metric_label})", f"{rata_total_sekolah:.2f}")
    kpi_c4.metric("📊 Standar Deviasi", f"{sd_total_sekolah:.2f}")

    # Tampilkan Tabel Statistik Deskriptif dan Chart Perbandingan
    col_stat_tbl, col_stat_chart = st.columns([3.2, 2.8])

    with col_stat_tbl:
        st.markdown("**📋 Ringkasan Parameter Statistik Per Mapel:**")
        st.dataframe(
            df_stat,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Jumlah Siswa (N)": st.column_config.NumberColumn(format="%d"),
                "Rata-rata (Mean)": st.column_config.NumberColumn(format="%.2f"),
                "Median": st.column_config.NumberColumn(format="%.2f"),
                "Standar Deviasi (SD)": st.column_config.NumberColumn(format="%.2f"),
                "Nilai Min": st.column_config.NumberColumn(format="%.2f"),
                "Nilai Max": st.column_config.NumberColumn(format="%.2f"),
                "Rentang (Range)": st.column_config.NumberColumn(format="%.2f"),
            }
        )

    with col_stat_chart:
        if not df_stat.empty and df_stat["Jumlah Siswa (N)"].sum() > 0:
            st.markdown("**📊 Visualisasi Rerata Nilai & Deviasi:**")
            fig_stat = go.Figure()
            fig_stat.add_trace(
                go.Bar(
                    x=df_stat["Mata Pelajaran"],
                    y=df_stat["Rata-rata (Mean)"],
                    error_y=dict(type="data", array=df_stat["Standar Deviasi (SD)"], visible=True),
                    marker=dict(
                        color=df_stat["Rata-rata (Mean)"],
                        colorscale="Blues",
                        showscale=False,
                    ),
                    text=df_stat["Rata-rata (Mean)"].apply(lambda x: f"{x:.2f}"),
                    textposition="auto",
                )
            )
            fig_stat.update_layout(
                margin=dict(l=20, r=20, t=20, b=40),
                height=260,
                xaxis_title="Mata Pelajaran",
                yaxis_title="Rata-rata Nilai",
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_stat, use_container_width=True)

    st.markdown("---")

    # --- 5. TABEL REKAP NILAI SISWA PER MATA PELAJARAN ---
    st.markdown("### 📋 Daftar Nilai Peserta Didik")
    st.caption("Data diurutkan berdasarkan `username` peserta didik secara ascending.")

    # Pivot Data: Satu baris per siswa dengan kolom nilai per mata pelajaran
    # Index: username, nisn, nama, jenis_kelamin
    # Columns: mapel
    # Values: metric_col
    bio_cols = ["username", "nisn", "nama", "jenis_kelamin"]
    for c in bio_cols:
        if c not in df_school.columns:
            df_school[c] = "-"

    # Agregasi jika ada duplikasi (username, mapel)
    df_school_agg = (
        df_school.groupby(["username", "nisn", "nama", "jenis_kelamin", "mapel"], as_index=False)
        .agg({metric_col: "mean"})
    )

    try:
        df_pivot = df_school_agg.pivot_table(
            index=["username", "nisn", "nama", "jenis_kelamin"],
            columns="mapel",
            values=metric_col,
            aggfunc="first",
        ).reset_index()
        df_pivot.columns.name = None
    except Exception as e_piv:
        st.error(f"Gagal memproses rekapitulasi nilai siswa: {e_piv}")
        return

    # Urutkan berdasarkan username secara ascending
    df_pivot = df_pivot.sort_values(by="username", ascending=True).reset_index(drop=True)

    # Identifikasi kolom mapel yang terbentuk
    subject_cols = [c for c in df_pivot.columns if c not in ["username", "nisn", "nama", "jenis_kelamin"]]

    # Hitung rata-rata nilai per siswa di seluruh mata pelajaran yang diikuti
    if subject_cols:
        df_pivot["Rata-Rata Siswa"] = df_pivot[subject_cols].mean(axis=1).round(2)
        # Bulatkan semua kolom nilai mapel
        for scol in subject_cols:
            df_pivot[scol] = pd.to_numeric(df_pivot[scol], errors="coerce").round(2)

    # Tambahkan kolom penomoran No
    df_pivot.insert(0, "No", range(1, len(df_pivot) + 1))

    # Rename kolom agar tampil formal dan ramah pengguna
    rename_cols = {
        "username": "Username",
        "nisn": "NISN",
        "nama": "Nama Siswa",
        "jenis_kelamin": "Jenis Kelamin",
    }
    df_display = df_pivot.rename(columns=rename_cols).copy()

    # Search bar untuk filter siswa secara interaktif
    col_search, col_cnt = st.columns([3.5, 2.5])
    with col_search:
        search_query = st.text_input(
            "🔍 Cari Siswa:",
            placeholder="Ketik username, NISN, atau nama siswa...",
            key="tab7_student_search",
        )

    if search_query:
        q = search_query.strip().lower()
        mask = (
            df_display["Username"].astype(str).str.lower().str.contains(q)
            | df_display["NISN"].astype(str).str.lower().str.contains(q)
            | df_display["Nama Siswa"].astype(str).str.lower().str.contains(q)
        )
        df_display_filtered = df_display[mask].reset_index(drop=True)
        # Renomor ulang hasil pencarian
        df_display_filtered["No"] = range(1, len(df_display_filtered) + 1)
    else:
        df_display_filtered = df_display

    with col_cnt:
        st.markdown(
            f"<div style='margin-top: 28px; color: #475569; font-weight: 500; font-size: 0.95rem;'>"
            f"Menampilkan <b>{len(df_display_filtered)}</b> dari <b>{len(df_display)}</b> siswa"
            f"</div>",
            unsafe_allow_html=True,
        )

    # Konfigurasi kolom untuk st.dataframe
    col_config = {
        "No": st.column_config.NumberColumn(width="small"),
        "Username": st.column_config.TextColumn(width="medium"),
        "NISN": st.column_config.TextColumn(width="medium"),
        "Nama Siswa": st.column_config.TextColumn(width="large"),
        "Jenis Kelamin": st.column_config.TextColumn(width="small"),
    }
    for scol in subject_cols:
        col_config[scol] = st.column_config.NumberColumn(format="%.2f")
    if "Rata-Rata Siswa" in df_display.columns:
        col_config["Rata-Rata Siswa"] = st.column_config.NumberColumn(
            label="Rata-Rata Siswa",
            format="%.2f"
        )

    # Tampilkan tabel utama
    st.dataframe(
        df_display_filtered,
        use_container_width=True,
        hide_index=True,
        column_config=col_config,
    )

    # --- 6. EKSPOR DATA (EXCEL & CSV) ---
    st.markdown("#### 📥 Unduh Laporan Rekapitulasi")
    
    clean_sch_slug = "".join(c if c.isalnum() else "_" for c in target_nm)[:30].strip("_")
    filename_base = f"rekap_nilai_{clean_sch_slug}_{target_kd}"

    c_dl1, c_dl2, c_dl3 = st.columns(3)

    with c_dl1:
        excel_bytes = convert_df_to_excel_bytes(df_display, sheet_name="Rekap_Nilai_Siswa")
        st.download_button(
            label="📊 Unduh Rekap Siswa (Excel .xlsx)",
            data=excel_bytes,
            file_name=f"{filename_base}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="btn_tab7_dl_excel",
        )

    with c_dl2:
        csv_bytes = convert_df_to_csv_bytes(df_display)
        st.download_button(
            label="📄 Unduh Rekap Siswa (CSV .csv)",
            data=csv_bytes,
            file_name=f"{filename_base}.csv",
            mime="text/csv",
            use_container_width=True,
            key="btn_tab7_dl_csv",
        )

    with c_dl3:
        excel_stat_bytes = convert_df_to_excel_bytes(df_stat, sheet_name="Statistik_Sekolah")
        st.download_button(
            label="📈 Unduh Statistik Sekolah (Excel)",
            data=excel_stat_bytes,
            file_name=f"statistik_{clean_sch_slug}_{target_kd}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="btn_tab7_dl_stat",
        )
