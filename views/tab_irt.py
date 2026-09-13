# tab_irt.py
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from equating import perform_multi_session_equating, run_cached_session_irt
from excel_exporter import convert_df_to_csv_bytes, create_excel_report
from irt_analysis import run_irt_analysis
from scoring import calculate_person_fit
from db_helper import prepare_and_save_analysis
from ui_components import render_irt_icc, render_irt_tif, render_wright_map


def _scale_theta_scores(df_persons, scale_min=200, scale_max=800):
    """Fungsi pembantu untuk mengonversi nilai theta ke skala nilai target (misal: 200-800)"""
    if df_persons is None or df_persons.empty:
        return df_persons

    theta_col = None
    for col in df_persons.columns:
        if col.lower() in [
            "kemampuan (theta θ)",
            "theta",
            "theta_ability",
            "ability",
            "skor_theta",
        ]:
            if not df_persons[col].isna().all():
                theta_col = col
                break
    if theta_col is None:
        numeric_cols = df_persons.select_dtypes(include=[np.number]).columns
        theta_col = numeric_cols[0] if len(numeric_cols) > 0 else df_persons.columns[0]

    t_min = df_persons[theta_col].min()
    t_max = df_persons[theta_col].max()

    df_res = df_persons.copy()
    if pd.notna(t_min) and pd.notna(t_max) and t_max != t_min:
        theta_arr = df_res[theta_col].values
        df_res["Nilai_Scaled"] = np.round(
            scale_min
            + ((theta_arr - t_min) / (t_max - t_min)) * (scale_max - scale_min),
            2,
        )
    else:
        df_res["Nilai_Scaled"] = (scale_min + scale_max) / 2.0

    return df_res


def _get_b_col(df_params):
    """Helper untuk mendeteksi kolom kesukaran (b) dengan presisi tinggi."""
    if df_params is None or df_params.empty:
        return None

    b_candidates = [
        c
        for c in df_params.columns
        if c.lower().strip()
        in [
            "b",
            "kesukaran",
            "difficulty",
            "b_param",
            "tingkat_kesukaran (b)",
            "tingkat_kesukaran",
            "tingkat_kesukaran_ctt",
            "diff",
        ]
    ]
    if b_candidates:
        return b_candidates[0]

    num_cols = df_params.iloc[:, 1:].select_dtypes(include=[np.number]).columns
    if len(num_cols) > 0:
        return num_cols[0]

    return df_params.columns[1] if len(df_params.columns) > 1 else df_params.columns[0]


def _auto_save_to_mysql(selected_model, df_matrix, df_params, df_persons_display, cache_data, scale_min, scale_max):
    """Fungsi internal untuk menyimpan otomatis hasil IRT langsung ke MySQL Database."""
    try:
        usr_col_name = df_matrix.columns[0]
        df_base = df_matrix[[usr_col_name]].copy()
        df_base["username"] = df_base[usr_col_name].astype(str).str.strip()
        df_base["username_clean"] = df_base["username"].str.lower()

        df_irt_save = df_persons_display.copy()
        
        # Cari kolom ID Peserta/username di dataframe hasil IRT
        id_col_irt = "ID Peserta" if "ID Peserta" in df_irt_save.columns else df_irt_save.columns[0]
        df_irt_save["username_clean"] = df_irt_save[id_col_irt].astype(str).str.strip().str.lower()

        skor_mentah_col = "Skor Mentah" if "Skor Mentah" in df_irt_save.columns else "skor_mentah"
        nilai_konv_col = "Nilai Konversi" if "Nilai Konversi" in df_irt_save.columns else "Nilai_Scaled"

        df_save_peserta = pd.merge(
            df_base[["username", "username_clean"]],
            df_irt_save[[c for c in ["username_clean", skor_mentah_col, nilai_konv_col] if c in df_irt_save.columns]],
            on="username_clean",
            how="left",
        )

        if skor_mentah_col in df_save_peserta.columns:
            df_save_peserta["skor_mentah"] = df_save_peserta[skor_mentah_col]
        
        col_target = f"skor_konversi_{selected_model.lower()}"
        if nilai_konv_col in df_save_peserta.columns:
            df_save_peserta[col_target] = df_save_peserta[nilai_konv_col]

        df_save_peserta = df_save_peserta.drop(columns=["username_clean", skor_mentah_col, nilai_konv_col], errors="ignore")

        # Format DataFrame Soal/Parameter ke skema tabel MySQL
        df_soal_to_save = df_params.copy()
        first_col = df_soal_to_save.columns[0]
        df_soal_to_save["kode_soal"] = df_soal_to_save[first_col]

        # Petakan kolom a, b, c ke kolom sesuai model IRT
        model_lower = selected_model.lower()
        b_found = _get_b_col(df_soal_to_save)

        if model_lower == "rasch":
            df_soal_to_save["b_rasch"] = df_soal_to_save[b_found] if b_found else None
        elif model_lower == "1pl":
            df_soal_to_save["b_1pl"] = df_soal_to_save[b_found] if b_found else None
        elif model_lower == "2pl":
            a_col = next((c for c in df_soal_to_save.columns if c.lower() in ["a", "daya_beda", "discrimination"]), None)
            df_soal_to_save["a_2pl"] = df_soal_to_save[a_col] if a_col else None
            df_soal_to_save["b_2pl"] = df_soal_to_save[b_found] if b_found else None
        elif model_lower == "3pl":
            a_col = next((c for c in df_soal_to_save.columns if c.lower() in ["a", "daya_beda", "discrimination"]), None)
            c_col = next((c for c in df_soal_to_save.columns if c.lower() in ["c", "guessing", "tebakan"]), None)
            df_soal_to_save["a_3pl"] = df_soal_to_save[a_col] if a_col else None
            df_soal_to_save["b_3pl"] = df_soal_to_save[b_found] if b_found else None
            df_soal_to_save["c_3pl"] = df_soal_to_save[c_col] if c_col else None

        fit_stats = cache_data.get("fit_stats", {})
        df_save_summary = pd.DataFrame(
            [
                {
                    "metode_model": selected_model.upper(),
                    "reliabilitas": fit_stats.get("reliability", 0.0),
                    "log_likelihood": fit_stats.get("log_likelihood", 0.0),
                    "aic": fit_stats.get("aic", 0.0),
                    "bic": fit_stats.get("bic", 0.0),
                }
            ]
        )

        success, msg = prepare_and_save_analysis(
            df_peserta=df_save_peserta,
            df_soal=df_soal_to_save,
            df_summary=df_save_summary,
            df_sekolah=pd.DataFrame(),
        )
        return success, msg
    except Exception as e:
        return False, str(e)


def render_tab_irt(df_matrix, dfs, ctt_res):
    st.subheader("Analisis Item Response Theory (IRT)")

    if df_matrix is None or df_matrix.empty:
        df_matrix = st.session_state.get("df_matrix")

    if df_matrix is None or df_matrix.empty:
        st.warning("⚠️ Data matriks belum siap untuk dianalisis IRT.")
        return

    # --- AMBIL KONFIGURASI SKALA DARI SIDEBAR ---
    scale_min = float(st.session_state.get("cfg_min_scale", 200.0))
    scale_max = float(st.session_state.get("cfg_max_scale", 800.0))

    selected_model = st.radio(
        "Pilih Model IRT:",
        options=["Rasch", "1PL", "2PL", "3PL"],
        key="selected_model_irt_radio",
        horizontal=True,
    )

    # --- RESET CACHE DENGAN DETEKSI PERUBAHAN KONFIGURASI SKALA ATAU MODEL ---
    current_config = f"{selected_model}_{scale_min}_{scale_max}"
    if st.session_state.get("last_irt_config") != current_config:
        st.session_state["last_irt_config"] = current_config
        st.session_state["irt_results"] = {}
        st.cache_data.clear()

    # --- NARASI DINAMIS UNTUK MODEL IRT YANG DIPILIH ---
    model_info = {
        "Rasch": {
            "title": "Model Rasch (1-Parameter Logistic / Equal Discrimination)",
            "purpose": "Mengukur kemampuan peserta dan tingkat kesulitan soal pada satu skala interval bersama (Logit) yang objektif dan bebas sampel.",
            "function": "Mengasumsikan semua soal memiliki daya beda yang seragam (dikunci konstan). Sangat ideal untuk tes standar, pengukuran yang berfokus pada keadilan (fairness), serta analisis Person Fit (mendeteksi tebakan/anomali).",
            "params": "1 Parameter: **Tingkat Kesukaran Soal ($b$)**",
        },
        "1PL": {
            "title": "Model 1PL (One-Parameter Logistic)",
            "purpose": "Memodelkan probabilitas jawaban benar hanya berdasarkan selisih antara kemampuan peserta ($\theta$) dan tingkat kesulitan soal ($b$).",
            "function": "Secara matematis serupa dengan Rasch, namun daya beda ($a$) diestimasi secara universal untuk seluruh perangkat soal. Berguna jika ingin mempertahankan kesederhanaan model IRT.",
            "params": "1 Parameter Utama: **Tingkat Kesukaran Soal ($b$)**",
        },
        "2PL": {
            "title": "Model 2PL (Two-Parameter Logistic)",
            "purpose": "Memodelkan respon peserta dengan memperhitungkan bahwa setiap soal memiliki kualitas/ketajaman pembeda yang berbeda-beda.",
            "function": "Sangat cocok untuk tes yang memiliki variasi kualitas soal, tes isian singkat, atau tes psikologi di mana tiap butir soal memiliki kontribusi pembeda peserta pandai dan kurang pandai yang tidak sama.",
            "params": "2 Parameter: **Tingkat Kesukaran Soal ($b$)** dan **Daya Beda Soal ($a$)**",
        },
        "3PL": {
            "title": "Model 3PL (Three-Parameter Logistic)",
            "purpose": "Memodelkan respon peserta pada tes pilihan ganda berisiko tinggi (high-stakes) dengan mengontrol faktor keberuntungan/tebakan acak.",
            "function": "Mencegah bias estimasi kemampuan ($\theta$) dan kesukaran ($b$) akibat peserta bertalenta rendah yang menjawab benar secara tidak sengaja melalui tebakan beruntung (pseudo-guessing).",
            "params": "3 Parameter: **Tingkat Kesukaran ($b$)**, **Daya Beda ($a$)**, dan **Tebakan Semu ($c$)**",
        },
    }

    current_info = model_info.get(selected_model, model_info["Rasch"])

    with st.expander(
        f"📖 **Tujuan & Fungsi {current_info['title']}**", expanded=False
    ):
        st.markdown(
            f"""
            * **Tujuan:** {current_info['purpose']}
            * **Fungsi Utama:** {current_info['function']}
            * **Parameter Terukur:** {current_info['params']}
            """
        )

    model_key = selected_model.lower()

    if "irt_results" not in st.session_state:
        st.session_state["irt_results"] = {}

    irt_results_store = st.session_state["irt_results"]

    # FLAG PENANDA APAKAH BARU SAJA DILAKUKAN REKALKULASI
    newly_calculated = False

    if (
        model_key not in irt_results_store
        or irt_results_store[model_key].get("df_person") is None
        or irt_results_store[model_key]["df_person"].empty
    ):
        with st.spinner(
            f"⏳ Menghitung estimasi IRT **{selected_model}** dan menyimpan ke MySQL..."
        ):
            try:
                res_calc = run_irt_analysis(
                    df_matrix,
                    model_type=selected_model,
                    min_scale=scale_min,
                    max_scale=scale_max,
                )
                irt_results_store[model_key] = {
                    "df_person": res_calc.get("person_params", pd.DataFrame()),
                    "item_params": res_calc.get("item_params", pd.DataFrame()),
                    "fit_stats": res_calc.get("fit_stats", {}),
                    "n_total": res_calc.get("n_total", len(df_matrix)),
                    "n_sample": res_calc.get(
                        "n_sample", len(res_calc.get("person_params", pd.DataFrame()))
                    ),
                }
                newly_calculated = True
            except Exception as e_calc:
                st.error(
                    f"❌ Gagal memproses estimasi IRT untuk model **{selected_model}**: {e_calc}"
                )
                return

    if "df_person" in irt_results_store[model_key] and not irt_results_store[
        model_key
    ]["df_person"].empty:
        irt_results_store[model_key]["df_person"] = _scale_theta_scores(
            irt_results_store[model_key]["df_person"], scale_min, scale_max
        )

    st.session_state["irt_results"] = irt_results_store

    cache_data = irt_results_store[model_key]
    df_persons_raw = cache_data["df_person"].copy()
    df_params = cache_data["item_params"].copy()
    n_total_pop = cache_data.get("n_total", len(df_matrix))
    n_sample_pop = cache_data.get("n_sample", len(df_persons_raw))

    irt_res = {"person_params": df_persons_raw, "item_params": df_params}

    # --- PENYETARAAN MULTI-SESI ---
    df_respon_raw = (
        dfs.get("respon", pd.DataFrame())
        if isinstance(dfs, dict)
        else pd.DataFrame()
    )

    col_sesi_candidate = None
    if not df_respon_raw.empty:
        col_sesi_candidate = next(
            (
                c
                for c in df_respon_raw.columns
                if c.lower().strip()
                in ["kode_sesi", "kodesesi", "sesi", "session_id", "session"]
            ),
            None,
        )

    equating_meta = {"is_multi_session": False}

    if col_sesi_candidate:
        unique_sessions = sorted(df_respon_raw[col_sesi_candidate].dropna().unique())
        if len(unique_sessions) > 1:
            st.markdown("---")
            st.markdown("### 🔄 Penyetaraan Multi-Sesi (Multi-Session Equating)")

            base_sess = st.selectbox(
                "Pilih Sesi Acuan (Base Session):",
                options=unique_sessions,
                index=0,
                help="Sesi acuan dijadikan standar skala. Sesi lainnya akan diselaraskan ke skala sesi acuan ini.",
            )

            user_id_col = next(
                (
                    c
                    for c in df_respon_raw.columns
                    if c.lower().strip() in ["username", "user_id", "id_peserta"]
                ),
                df_respon_raw.columns[0],
            )

            session_irt_results = {}
            for sess in unique_sessions:
                users_in_sess = (
                    df_respon_raw[df_respon_raw[col_sesi_candidate] == sess][
                        user_id_col
                    ]
                    .astype(str)
                    .str.strip()
                    .str.lower()
                    .tolist()
                )
                id_col_m = df_matrix.columns[0]
                df_sub_matrix = df_matrix[
                    df_matrix[id_col_m]
                    .astype(str)
                    .str.strip()
                    .str.lower()
                    .isin(users_in_sess)
                ].copy()

                if not df_sub_matrix.empty:
                    session_irt_results[sess] = run_cached_session_irt(
                        df_sub_matrix, model_type=selected_model
                    )

            equated_results, equating_meta = perform_multi_session_equating(
                df_responses=df_respon_raw,
                session_irt_results=session_irt_results,
                base_session_id=base_sess,
            )

            if equating_meta.get("is_multi_session", False):
                st.subheader("📊 Hasil Evaluasi Psikometri & Penyetaraan Multi-Sesi")

                for sess_id, report in equating_meta.get("reports", {}).items():
                    with st.expander(
                        f"📌 Ringkasan Penyetaraan: Sesi {sess_id} ➔ Sesi {base_sess}",
                        expanded=True,
                    ):
                        if report.get("status") == "SUCCESS":
                            col1, col2, col3 = st.columns(3)
                            col1.metric(
                                "Soal Jangkar",
                                f"{report.get('n_anchor', 0)} Butir",
                                f"{report.get('anchor_ratio', 0.0):.1f}%",
                            )
                            col2.metric(
                                "Korelasi Kesukaran (r)",
                                f"{report.get('correlation', 0.0):.2f}",
                            )
                            col3.metric(
                                "Konstanta (A / B)",
                                f"{report.get('A', 1.0):.3f} / {report.get('B', 0.0):.3f}",
                            )

                            st.markdown("**Catatan Evaluasi Psikometri:**")
                            for warn in report.get("warnings", []):
                                st.markdown(warn)
                        else:
                            st.error(
                                report.get(
                                    "warnings", ["Gagal melakukan penyetaraan."]
                                )[0]
                            )
            st.markdown("---")

    id_col = df_matrix.columns[0]
    skor_col_name = "skor_mentah"

    df_params = irt_res.get("item_params", pd.DataFrame()).copy()
    df_persons = irt_res.get("person_params", pd.DataFrame()).copy()

    if not df_params.empty:
        param_item_col = df_params.columns[0]
        df_params = df_params[
            ~df_params[param_item_col]
            .astype(str)
            .str.lower()
            .isin(["jumlah_soal", "jumlahsoal"])
        ].copy()

    theta_col = None
    if not df_persons.empty:
        for col in df_persons.columns:
            if col.lower() in [
                "kemampuan (theta θ)",
                "theta",
                "theta_ability",
                "ability",
                "skor_theta",
            ]:
                if not df_persons[col].isna().all():
                    theta_col = col
                    break
        if theta_col is None:
            numeric_cols = df_persons.select_dtypes(include=[np.number]).columns
            theta_col = (
                numeric_cols[0]
                if len(numeric_cols) > 0
                else (
                    df_persons.columns[1]
                    if len(df_persons.columns) > 1
                    else df_persons.columns[0]
                )
            )

    df_persons_display = df_persons.copy()
    b_col = _get_b_col(df_params)

    if not df_persons_display.empty:
        person_id_col = df_persons_display.columns[0]

        if skor_col_name in df_matrix.columns:
            score_map = dict(
                zip(df_matrix[id_col].astype(str), df_matrix[skor_col_name])
            )
        else:
            numeric_matrix = df_matrix.iloc[:, 1:].apply(
                pd.to_numeric, errors="coerce"
            )
            score_map = dict(
                zip(df_matrix[id_col].astype(str), numeric_matrix.sum(axis=1))
            )

        df_persons_display["Skor Mentah"] = (
            df_persons_display[person_id_col].astype(str).map(score_map)
        )

        df_fit = calculate_person_fit(df_matrix, df_params, b_col=b_col)

        df_persons_display[person_id_col] = (
            df_persons_display[person_id_col].astype(str).str.strip()
        )

        if not df_fit.empty and id_col in df_fit.columns:
            df_fit[id_col] = df_fit[id_col].astype(str).str.strip()

            fit_cols = [id_col]
            for col_fit_target in ["Outfit_MSQ", "Status_Pola_Jawab"]:
                if col_fit_target in df_fit.columns:
                    fit_cols.append(col_fit_target)

            df_persons_display = df_persons_display.merge(
                df_fit[fit_cols], left_on=person_id_col, right_on=id_col, how="left"
            )
        else:
            df_persons_display["Outfit_MSQ"] = np.nan
            df_persons_display["Status_Pola_Jawab"] = "Tidak Terhitung"

        rename_dict = {}
        if person_id_col != "ID Peserta":
            rename_dict[person_id_col] = "ID Peserta"

        if theta_col and theta_col != "Kemampuan (Theta θ)":
            rename_dict[theta_col] = "Kemampuan (Theta θ)"

        df_persons_display = df_persons_display.rename(columns=rename_dict)

        if "Nilai_Scaled" in df_persons_display.columns:
            df_persons_display["Nilai Konversi"] = df_persons_display["Nilai_Scaled"]

        df_persons_display = df_persons_display.loc[
            :, ~df_persons_display.columns.duplicated()
        ]

        target_cols = [
            "ID Peserta",
            "Skor Mentah",
            "Kemampuan (Theta θ)",
            "Nilai Konversi",
            "Outfit_MSQ",
            "Status_Pola_Jawab",
        ]
        if "SEM" in df_persons_display.columns:
            target_cols.append("SEM")

        df_irt_final = df_persons_display[
            [c for c in target_cols if c in df_persons_display.columns]
        ].copy()
        df_irt_final = df_irt_final.loc[:, ~df_irt_final.columns.duplicated()]

        if "No." not in df_irt_final.columns:
            df_irt_final.insert(0, "No.", range(1, 1 + len(df_irt_final)))
    else:
        df_irt_final = pd.DataFrame()

    # --- SIMPAN OTOMATIS KE MYSQL (SETELAH DF_IRT_FINAL SELESAI DIRAKIT) ---
    if newly_calculated and not df_irt_final.empty:
        success_auto, msg_auto = _auto_save_to_mysql(
            selected_model=selected_model,
            df_matrix=df_matrix,
            df_params=df_params,
            df_persons_display=df_irt_final,
            cache_data=cache_data,
            scale_min=scale_min,
            scale_max=scale_max,
        )
        if success_auto:
            st.success(
                f"✅ Data hasil kalkulasi IRT ({selected_model}) otomatis tersimpan ke MySQL Server!"
            )
        else:
            st.warning(f"⚠️ Gagal melakukan penyimpanan otomatis ke MySQL: {msg_auto}")

    if not df_persons.empty and theta_col in df_persons.columns:
        st.markdown("#### 📊 Statistik Deskriptif Estimasi Ability (Theta θ)")

        theta_vals = pd.to_numeric(df_persons[theta_col], errors="coerce").dropna()
        scaled_vals = (
            pd.to_numeric(df_persons["Nilai_Scaled"], errors="coerce").dropna()
            if "Nilai_Scaled" in df_persons.columns
            else pd.Series()
        )

        desc_data = {
            "Metrik Statistik": [
                "Jumlah Peserta Asli (N_total)",
                "Jumlah Peserta Sampel (N_sampel)",
                "Rata-rata (Mean)",
                "Standar Deviasi (SD)",
                "Nilai Minimum",
                "Kuartil 1 (Q1 - 25%)",
                "Median (Q2 - 50%)",
                "Kuartil 3 (Q3 - 75%)",
                "Nilai Maksimum",
                "Kemiringan (Skewness)",
                "Keruncingan (Kurtosis)",
            ],
            "Skala Theta (θ)": [
                f"{n_total_pop:,}",
                f"{n_sample_pop:,}",
                f"{theta_vals.mean():.3f}",
                f"{theta_vals.std():.3f}",
                f"{theta_vals.min():.3f}",
                f"{theta_vals.quantile(0.25):.3f}",
                f"{theta_vals.median():.3f}",
                f"{theta_vals.quantile(0.75):.3f}",
                f"{theta_vals.max():.3f}",
                f"{theta_vals.skew():.3f}",
                f"{theta_vals.kurtosis():.3f}",
            ],
        }

        if not scaled_vals.empty:
            desc_data[f"Skala Konversi ({scale_min} - {scale_max})"] = [
                f"{n_total_pop:,}",
                f"{n_sample_pop:,}",
                f"{scaled_vals.mean():.2f}",
                f"{scaled_vals.std():.2f}",
                f"{scaled_vals.min():.2f}",
                f"{scaled_vals.quantile(0.25):.2f}",
                f"{scaled_vals.median():.2f}",
                f"{scaled_vals.quantile(0.75):.2f}",
                f"{scaled_vals.max():.2f}",
                f"{scaled_vals.skew():.3f}",
                f"{scaled_vals.kurtosis():.3f}",
            ]

        df_desc = pd.DataFrame(desc_data)
        table_height = (len(df_desc) + 1) * 35 + 10

        st.dataframe(
            df_desc,
            use_container_width=True,
            hide_index=True,
            height=table_height,
        )
        st.divider()

    # --- GRAFIK DISTRIBUSI ---
    if not df_persons.empty and "Nilai_Scaled" in df_persons.columns:
        st.markdown(
            f"#### 📈 Grafik Distribusi Nilai Konversi Peserta (Model: {selected_model})"
        )

        st.caption(
            "🎯 **Tujuan:** Menampilkan gambaran umum sebaran skor/nilai hasil konversi seluruh peserta tes."
        )

        with st.expander(
            "📖 Cara Membaca Grafik Distribusi Nilai Konversi", expanded=False
        ):
            st.markdown(
                """
            * **Batang Grafik (Histogram):** Menunjukkan jumlah peserta pada rentang nilai tertentu. Jika puncak grafik berada di tengah, sebaran nilai peserta tergolong normal dan seimbang.
            * **Boxplot (Garis/Kotak di Atas):** Menunjukkan nilai tengah (*median*), rentang 50% nilai peserta terbanyak (kotak utama), serta nilai tertinggi, terendah, dan pencilan (*outlier*).
            """
            )

        chart_data = (
            df_persons["Nilai_Scaled"].sample(n=30000, random_state=42)
            if len(df_persons) > 30000
            else df_persons["Nilai_Scaled"]
        ).dropna()

        fig_dist_irt = px.histogram(
            chart_data,
            x="Nilai_Scaled",
            nbins=30,
            title=f"<b>Distribusi Nilai Konversi Peserta (Skala {scale_min} - {scale_max})</b>",
            labels={"Nilai_Scaled": "Nilai Konversi", "count": "Jumlah Peserta"},
            color_discrete_sequence=["#00CC96"],
            marginal="box",
        )

        fig_dist_irt.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis_title="<b>Nilai Konversi</b>",
            yaxis_title="<b>Jumlah Peserta</b>",
            bargap=0.08,
        )

        st.plotly_chart(fig_dist_irt, use_container_width=True)
        st.divider()

    # --- GRAFIK ICC, TIF, DAN WRIGHT MAP ---
    if not df_params.empty:
        item_col_name = df_params.columns[0]
        all_items = df_params[item_col_name].astype(str).tolist()
        selected_items = st.multiselect(
            "Filter Soal untuk Menampilkan ICC:",
            options=all_items,
            default=all_items[:5] if len(all_items) >= 5 else all_items,
            key="icc_filter_soal",
        )

        st.markdown(
            f"#### Item Characteristic Curves (ICC) - Model {selected_model}"
        )
        st.caption(
            "🎯 **Tujuan:** Mengetahui tingkat kesulitan dan daya beda dari masing-masing butir soal secara individual."
        )
        with st.expander("📖 Cara Membaca Kurva ICC", expanded=False):
            st.markdown(
                """
            * **Sumbu Horizontal (Bawah):** Kemampuan peserta ($\theta$). Semakin ke kanan, peserta semakin pandai.
            * **Sumbu Vertikal (Kiri):** Peluang menjawab benar (0,0 = 0% hingga 1,0 = 100%).
            * **Posisi Kurva Soal:**
              * Kurva di sebelah **kiri** menandakan **soal mudah**.
              * Kurva di sebelah **kanan** menandakan **soal sulit** (hanya peserta berkemampuan tinggi yang berpeluang besar menjawab benar).
            """
            )

        fig_icc = render_irt_icc(df_params, selected_items, selected_model, b_col)
        st.plotly_chart(fig_icc, use_container_width=True)

        st.divider()

        col_chart1, col_chart2 = st.columns(2)

        with col_chart1:
            st.markdown("#### Test Information Function (TIF) & SEM")
            st.caption(
                "🎯 **Tujuan:** Mengukur sejauh mana seluruh perangkat soal dapat mengukur kemampuan peserta secara akurat."
            )
            with st.expander("📖 Cara Membaca Grafik TIF & SEM", expanded=False):
                st.markdown(
                    """
                * **Garis Informasi / TIF (Biru):** Semakin tinggi puncaknya, semakin akurat tes tersebut mengukur peserta pada tingkat kemampuan tersebut.
                * **Garis Kesalahan / SEM (Merah):** Menunjukkan tingkat kesalahan pengukuran.
                * **Kondisi Ideal:** Pada area di mana garis TIF tinggi, garis SEM harus berada di posisi paling rendah.
                """
                )
            fig_tif = render_irt_tif(df_params, selected_model, b_col)
            st.plotly_chart(fig_tif, use_container_width=True)

        with col_chart2:
            st.markdown("#### Wright Map (Peta Peserta & Soal)")
            st.caption(
                "🎯 **Tujuan:** Membandingan tingkat kemampuan peserta dengan tingkat kesulitan soal pada satu skala yang sama."
            )
            with st.expander("📖 Cara Membaca Wright Map", expanded=False):
                st.markdown(
                    """
                * **Sebaran Peserta (Kiri):** Titik/kotak menunjukkan posisi kemampuan peserta. Semakin tinggi posisinya, semakin tinggi kemampuan pesertanya.
                * **Sebaran Soal (Kanan):** Menunjukkan posisi tingkat kesulitan soal. Semakin tinggi posisinya, semakin sulit soal tersebut.
                * **Evaluasi Sebaran:** Jika sebaran peserta dan soal sejajar/berada pada rentang yang sama, artinya instrumen tes ini **sangat ideal** untuk populasi peserta tersebut.
                """
                )
            df_persons_wright = (
                df_persons.sample(n=5000, random_state=42)
                if len(df_persons) > 5000
                else df_persons
            )
            fig_wright = render_wright_map(
                df_persons_wright, df_params, theta_col, b_col
            )
            st.plotly_chart(fig_wright, use_container_width=True)

    st.divider()
    col_irt_item, col_irt_person = st.columns(2)
    with col_irt_item:
        st.write("**Parameter Soal (IRT):**")
        df_params_display = df_params.copy()

        # 1. Ambil kolom ID soal pertama sebagai acuan utama
        first_col = df_params_display.columns[0]

        # 2. Hapus semua kolom variasi nama soal yang tidak diperlukan
        cols_to_drop = [
            c for c in df_params_display.columns 
            if c.lower().strip() in ["item", "kode_soal", "kode_item"] and c != first_col
        ]
        df_params_display = df_params_display.drop(columns=cols_to_drop, errors="ignore")

        # 3. Hapus kolom dengan nama persis atau insensitive case duplikat
        df_params_display = df_params_display.loc[:, ~df_params_display.columns.str.lower().duplicated()]

        # 4. Standarkan nama kolom acuan utama menjadi "Kode Soal"
        df_params_display = df_params_display.rename(columns={first_col: "Kode Soal"})

        # 5. Tambahkan nomor urut (No.) di posisi pertama
        if "No." not in df_params_display.columns:
            df_params_display.insert(0, "No.", range(1, 1 + len(df_params_display)))

        st.dataframe(df_params_display, use_container_width=True, hide_index=True)

    with col_irt_person:
        st.write("**Estimasi Kemampuan Peserta & Person Fit (Anomali):**")
        st.dataframe(
            df_irt_final.head(100), use_container_width=True, hide_index=True
        )
        st.caption("⚡ Menampilkan 100 sampel data pertama untuk efisiensi memori UI.")

    st.divider()
    st.subheader("💾 Unduh Hasil Analisis IRT")

    col_dl1, col_dl2 = st.columns(2)

    with col_dl1:
        df_items = (
            ctt_res.get("item_stats", pd.DataFrame())
            if isinstance(ctt_res, dict)
            else pd.DataFrame()
        )
        excel_data = create_excel_report(
            df_matrix=df_matrix,
            df_items=df_items,
            df_dist=(
                ctt_res.get("distractor_stats", pd.DataFrame())
                if isinstance(ctt_res, dict)
                else pd.DataFrame()
            ),
            df_params=df_params,
            df_persons_irt=df_irt_final,
            equating_meta=equating_meta,
        )
        st.download_button(
            label="📊 Download Excel (.xlsx)",
            data=excel_data,
            file_name=f"Laporan_Psikometri_Item_{selected_model}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="btn_dl_excel",
        )

    with col_dl2:
        csv_data_person = convert_df_to_csv_bytes(df_irt_final)
        st.download_button(
            label="📄 Download CSV Peserta (.csv)",
            data=csv_data_person,
            file_name=f"Hasil_Nilai_Peserta_Lengkap_{selected_model}.csv",
            mime="text/csv",
            use_container_width=True,
            key="btn_dl_csv",
        )