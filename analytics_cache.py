# analytics_cache.py
"""
Modul pra-komputasi dan caching analitik untuk mempercepat visualisasi dashboard:
Menyimpan tabel agregasi terkomputasi komplit (CTT, IRT, Sekolah, Wilayah, Hierarki Geo)
ke memori dan disk (Parquet) sehingga pergantian filter (mapel, model IRT, provinsi, kabupaten,
minimal peserta, dan sekolah) berjalan instan tanpa menghitung ulang data populasi jutaan baris.
"""

import os
import json
import numpy as np
import pandas as pd
import streamlit as st

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")


def get_cache_dir() -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return CACHE_DIR


def compute_ctt_precomputed(df_peserta: pd.DataFrame, ctt_res: dict = None, mapel_lookup: dict = None) -> dict:
    """Menghitung ringkasan statistik deskriptif CTT per mata pelajaran sekali di awal."""
    res = {}
    if df_peserta is None or df_peserta.empty:
        return res

    score_col = None
    for cand in ["skor_konversi_ctt", "Nilai_Konversi", "skor_mentah"]:
        if cand in df_peserta.columns and df_peserta[cand].notna().any():
            score_col = cand
            break

    if not score_col:
        return res

    mapel_col = "mapel" if "mapel" in df_peserta.columns else None
    mapels = []
    if mapel_col:
        mapels = [
            str(m).strip()
            for m in df_peserta[mapel_col].dropna().unique()
            if str(m).strip() not in ["", "nan", "None", "-"]
        ]

    alpha_map = ctt_res.get("alpha_by_mapel", {}) if ctt_res else {}
    global_alpha = ctt_res.get("cronbach_alpha", ctt_res.get("reliability", 0.0)) if ctt_res else 0.0

    # 1. Hitung untuk tiap mata pelajaran
    for m in mapels:
        s = pd.to_numeric(df_peserta[df_peserta[mapel_col] == m][score_col], errors="coerce").dropna()
        if not s.empty:
            q1 = float(s.quantile(0.25))
            med = float(s.median())
            q3 = float(s.quantile(0.75))
            skew = float(s.skew()) if len(s) > 2 else 0.0
            kurt = float(s.kurtosis()) if len(s) > 3 else 0.0
            alpha = float(alpha_map.get(m, global_alpha))

            res[m] = {
                "N": int(len(s)),
                "Mean": float(s.mean()),
                "SD": float(s.std()) if len(s) > 1 else 0.0,
                "Min": float(s.min()),
                "Q1": q1,
                "Median": med,
                "Q3": q3,
                "Max": float(s.max()),
                "Skew": skew,
                "Kurt": kurt,
                "Alpha": alpha,
            }

    # 2. Hitung untuk semua gabungan (ALL)
    s_all = pd.to_numeric(df_peserta[score_col], errors="coerce").dropna()
    if not s_all.empty:
        res["ALL"] = {
            "N": int(len(s_all)),
            "Mean": float(s_all.mean()),
            "SD": float(s_all.std()) if len(s_all) > 1 else 0.0,
            "Min": float(s_all.min()),
            "Q1": float(s_all.quantile(0.25)),
            "Median": float(s_all.median()),
            "Q3": float(s_all.quantile(0.75)),
            "Max": float(s_all.max()),
            "Skew": float(s_all.skew()) if len(s_all) > 2 else 0.0,
            "Kurt": float(s_all.kurtosis()) if len(s_all) > 3 else 0.0,
            "Alpha": float(global_alpha),
        }

    return res


def compute_irt_precomputed(
    df_peserta: pd.DataFrame,
    scale_config: dict = None,
) -> dict:
    """Menghitung ringkasan parameter ability IRT (Rasch, 1PL, 2PL, 3PL) per mapel sekali di awal."""
    res = {}
    if df_peserta is None or df_peserta.empty:
        return res

    cfg_mean = float(scale_config.get("mean", 500.0)) if scale_config else 500.0
    cfg_sd = float(scale_config.get("sd", 100.0)) if scale_config else 100.0

    mapel_col = "mapel" if "mapel" in df_peserta.columns else None
    mapels = []
    if mapel_col:
        mapels = [
            str(m).strip()
            for m in df_peserta[mapel_col].dropna().unique()
            if str(m).strip() not in ["", "nan", "None", "-"]
        ]

    for model in ["rasch", "1pl", "2pl", "3pl"]:
        col_name = f"skor_konversi_{model}"
        if col_name not in df_peserta.columns or df_peserta[col_name].isna().all():
            continue

        # Per Mapel
        for m in mapels:
            s = pd.to_numeric(df_peserta[df_peserta[mapel_col] == m][col_name], errors="coerce").dropna()
            if not s.empty:
                theta = np.round((s - cfg_mean) / max(cfg_sd, 1e-5), 3)
                res[(model, m)] = {
                    "N_total": int(len(s)),
                    "N_sample": int(len(s)),
                    "mean_theta": float(theta.mean()),
                    "sd_theta": float(theta.std()) if len(theta) > 1 else 0.0,
                    "min_theta": float(theta.min()),
                    "q1_theta": float(theta.quantile(0.25)),
                    "med_theta": float(theta.median()),
                    "q3_theta": float(theta.quantile(0.75)),
                    "max_theta": float(theta.max()),
                    "mean_conv": float(s.mean()),
                    "sd_conv": float(s.std()) if len(s) > 1 else 0.0,
                    "min_conv": float(s.min()),
                    "q1_conv": float(s.quantile(0.25)),
                    "med_conv": float(s.median()),
                    "q3_conv": float(s.quantile(0.75)),
                    "max_conv": float(s.max()),
                }

        # Keseluruhan
        s_all = pd.to_numeric(df_peserta[col_name], errors="coerce").dropna()
        if not s_all.empty:
            th_all = np.round((s_all - cfg_mean) / max(cfg_sd, 1e-5), 3)
            res[(model, "ALL")] = {
                "N_total": int(len(s_all)),
                "N_sample": int(len(s_all)),
                "mean_theta": float(th_all.mean()),
                "sd_theta": float(th_all.std()) if len(th_all) > 1 else 0.0,
                "min_theta": float(th_all.min()),
                "q1_theta": float(th_all.quantile(0.25)),
                "med_theta": float(th_all.median()),
                "q3_theta": float(th_all.quantile(0.75)),
                "max_theta": float(th_all.max()),
                "mean_conv": float(s_all.mean()),
                "sd_conv": float(s_all.std()) if len(s_all) > 1 else 0.0,
                "min_conv": float(s_all.min()),
                "q1_conv": float(s_all.quantile(0.25)),
                "med_conv": float(s_all.median()),
                "q3_conv": float(s_all.quantile(0.75)),
                "max_conv": float(s_all.max()),
            }

    return res


def compute_school_tables(df_peserta: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Menghasilkan dua tabel agregasi sekolah:
    1. df_school_by_mapel: Agregasi per (sekolah, mapel) (~100k baris)
    2. df_school_composite: Agregasi sekolah gabungan rata-rata komposit siswa (36.582 baris)
    """
    if df_peserta is None or df_peserta.empty:
        return pd.DataFrame(), pd.DataFrame()

    df_clean = df_peserta.copy()
    user_col = "username" if "username" in df_clean.columns else df_clean.columns[0]
    sek_col = "kode_sekolah" if "kode_sekolah" in df_clean.columns else "_school_key"
    if sek_col not in df_clean.columns:
        df_clean["kode_sekolah"] = df_clean[user_col].astype(str).str[:9].str.upper()
        sek_col = "kode_sekolah"

    base_cols = ["kode_sekolah", "nama_sekolah", "nama_kabupaten", "nama_provinsi", "kode_provinsi"]
    for c in base_cols:
        if c not in df_clean.columns:
            df_clean[c] = "-"

    score_cols = [
        "skor_mentah", "skor_konversi_ctt", "skor_konversi_rasch",
        "skor_konversi_1pl", "skor_konversi_2pl", "skor_konversi_3pl"
    ]
    present_scores = [c for c in score_cols if c in df_clean.columns]
    for c in present_scores:
        df_clean[c] = pd.to_numeric(df_clean[c], errors="coerce")

    # 1. df_school_by_mapel
    if "mapel" in df_clean.columns:
        agg_dict_m = {user_col: "nunique"}
        for sc in present_scores:
            agg_dict_m[sc] = "mean"

        grp_cols_m = base_cols + ["mapel"]
        df_school_by_mapel = (
            df_clean.groupby(grp_cols_m, as_index=False)
            .agg(agg_dict_m)
            .rename(columns={user_col: "jumlah_peserta"})
        )
        for sc in present_scores:
            df_school_by_mapel[sc] = df_school_by_mapel[sc].round(2)
    else:
        df_school_by_mapel = pd.DataFrame()

    # 2. df_school_composite (rata-rata nilai per peserta terlebih dahulu lalu per sekolah)
    grp_student = [user_col] + base_cols
    agg_student = {sc: "mean" for sc in present_scores}
    df_student_comp = df_clean.groupby(grp_student, as_index=False).agg(agg_student)

    agg_school = {user_col: "count"}
    for sc in present_scores:
        agg_school[sc] = "mean"

    df_school_composite = (
        df_student_comp.groupby(base_cols, as_index=False)
        .agg(agg_school)
        .rename(columns={user_col: "jumlah_peserta"})
    )
    for sc in present_scores:
        df_school_composite[sc] = df_school_composite[sc].round(2)

    df_school_composite["mapel"] = "GABUNGAN"

    return df_school_by_mapel, df_school_composite


def compute_region_tables(df_peserta: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Menghitung agregasi statistik wilayah (Provinsi ~38 baris & Kabupaten ~514 baris)
    untuk semua metrik dan mapel sekali di awal.
    """
    if df_peserta is None or df_peserta.empty:
        return pd.DataFrame(), pd.DataFrame()

    df_clean = df_peserta.copy()
    user_col = "username" if "username" in df_clean.columns else df_clean.columns[0]

    for c in ["kode_provinsi", "nama_provinsi", "nama_kabupaten"]:
        if c not in df_clean.columns:
            df_clean[c] = "-"

    metric_mapping = {
        "Klasik / CTT (Skala 0-100)": "skor_konversi_ctt",
        "IRT RASCH (Skala Konversi)": "skor_konversi_rasch",
        "IRT 1PL (Skala Konversi)": "skor_konversi_1pl",
        "IRT 2PL (Skala Konversi)": "skor_konversi_2pl",
        "IRT 3PL (Skala Konversi)": "skor_konversi_3pl",
    }
    available_metrics = {
        label: col for label, col in metric_mapping.items()
        if col in df_clean.columns and df_clean[col].notna().any()
    }

    if not available_metrics:
        if "skor_mentah" in df_clean.columns:
            available_metrics["Skor Mentah"] = "skor_mentah"

    mapels = []
    if "mapel" in df_clean.columns:
        mapels = [
            str(m).strip()
            for m in df_clean["mapel"].dropna().unique()
            if str(m).strip() not in ["", "nan", "None", "-"]
        ]

    prov_rows = []
    kab_rows = []

    def _agg_block(df_in, grp_cols, mapel_tag, metric_label, col_val):
        s_df = df_in.dropna(subset=[col_val]).copy()
        s_df[col_val] = pd.to_numeric(s_df[col_val], errors="coerce")
        if s_df.empty:
            return pd.DataFrame()

        agg_df = (
            s_df.groupby(grp_cols)[col_val]
            .agg(
                Jumlah_Peserta="count",
                Rata_Rata="mean",
                SD="std",
                Min="min",
                Q1=lambda x: x.quantile(0.25),
                Median="median",
                Q3=lambda x: x.quantile(0.75),
                Max="max",
            )
            .reset_index()
        )
        agg_df["SD"] = agg_df["SD"].fillna(0.0)
        num_cols = ["Rata_Rata", "SD", "Min", "Q1", "Median", "Q3", "Max"]
        agg_df[num_cols] = agg_df[num_cols].round(2)
        agg_df["mapel"] = mapel_tag
        agg_df["metric"] = metric_label
        return agg_df

    # A. Per Mapel Tunggal
    for m in mapels:
        df_m = df_clean[df_clean["mapel"] == m]
        for m_label, m_col in available_metrics.items():
            # Provinsi
            p_agg = _agg_block(df_m, ["kode_provinsi", "nama_provinsi"], m, m_label, m_col)
            if not p_agg.empty:
                prov_rows.append(p_agg)
            # Kabupaten
            k_agg = _agg_block(df_m, ["kode_provinsi", "nama_provinsi", "nama_kabupaten"], m, m_label, m_col)
            if not k_agg.empty:
                kab_rows.append(k_agg)

    # B. Gabungan (Semua Mapel) - Komposit per Peserta
    if len(mapels) > 1:
        grp_user = [user_col, "kode_provinsi", "nama_provinsi", "nama_kabupaten"]
        cols_calc = list(available_metrics.values())
        df_user_comp = df_clean.groupby(grp_user, as_index=False)[cols_calc].mean()
        for m_label, m_col in available_metrics.items():
            p_agg = _agg_block(df_user_comp, ["kode_provinsi", "nama_provinsi"], "GABUNGAN", m_label, m_col)
            if not p_agg.empty:
                prov_rows.append(p_agg)
            k_agg = _agg_block(df_user_comp, ["kode_provinsi", "nama_provinsi", "nama_kabupaten"], "GABUNGAN", m_label, m_col)
            if not k_agg.empty:
                kab_rows.append(k_agg)

    df_prov_all = pd.concat(prov_rows, ignore_index=True) if prov_rows else pd.DataFrame()
    df_kab_all = pd.concat(kab_rows, ignore_index=True) if kab_rows else pd.DataFrame()

    return df_prov_all, df_kab_all


def compute_geo_hierarchy(df_peserta: pd.DataFrame) -> pd.DataFrame:
    """Membangun hierarki wilayah & sekolah unik (Provinsi -> Kabupaten -> Sekolah) untuk Tab 7."""
    if df_peserta is None or df_peserta.empty:
        return pd.DataFrame()

    cols = ["kode_provinsi", "nama_provinsi", "nama_kabupaten", "kode_sekolah", "nama_sekolah"]
    for c in cols:
        if c not in df_peserta.columns:
            df_peserta[c] = "-"

    df_h = df_peserta[cols].dropna().drop_duplicates().copy()
    for c in cols:
        df_h[c] = df_h[c].astype(str).str.strip()

    df_h = df_h[~df_h["nama_provinsi"].isin(["", "-", "nan", "None", "TIDAK TERDEFINISI"])]
    df_h = df_h[~df_h["nama_kabupaten"].isin(["", "-", "nan", "None", "TIDAK TERDEFINISI"])]
    return df_h.sort_values(by=["nama_provinsi", "nama_kabupaten", "nama_sekolah"])


def save_analytics_cache(
    ctt_dict: dict = None,
    irt_dict: dict = None,
    df_school_m: pd.DataFrame = None,
    df_school_comp: pd.DataFrame = None,
    df_prov_reg: pd.DataFrame = None,
    df_kab_reg: pd.DataFrame = None,
    df_geo_h: pd.DataFrame = None,
) -> bool:
    """Menyimpan seluruh tabel dan ringkasan terkomputasi ke cache disk Parquet/JSON."""
    cdir = get_cache_dir()
    try:
        if ctt_dict is not None:
            with open(os.path.join(cdir, "ctt_summary.json"), "w", encoding="utf-8") as f:
                json.dump(ctt_dict, f, indent=2)

        if irt_dict is not None:
            # Serialisasi key tuple (model, mapel) -> str
            serial_irt = {f"{k[0]}___{k[1]}": v for k, v in irt_dict.items()}
            with open(os.path.join(cdir, "irt_summary.json"), "w", encoding="utf-8") as f:
                json.dump(serial_irt, f, indent=2)

        if df_school_m is not None and not df_school_m.empty:
            df_school_m.to_parquet(os.path.join(cdir, "school_by_mapel.parquet"), index=False)

        if df_school_comp is not None and not df_school_comp.empty:
            df_school_comp.to_parquet(os.path.join(cdir, "school_composite.parquet"), index=False)

        if df_prov_reg is not None and not df_prov_reg.empty:
            df_prov_reg.to_parquet(os.path.join(cdir, "region_prov.parquet"), index=False)

        if df_kab_reg is not None and not df_kab_reg.empty:
            df_kab_reg.to_parquet(os.path.join(cdir, "region_kab.parquet"), index=False)

        if df_geo_h is not None and not df_geo_h.empty:
            df_geo_h.to_parquet(os.path.join(cdir, "geo_hierarchy.parquet"), index=False)

        return True
    except Exception as e:
        print(f"Catatan simpan cache analitik: {e}")
        return False


def load_analytics_cache() -> dict:
    """Membaca cache analitik dari disk Parquet/JSON jika tersedia."""
    cdir = get_cache_dir()
    res = {}
    try:
        f_ctt = os.path.join(cdir, "ctt_summary.json")
        if os.path.exists(f_ctt):
            with open(f_ctt, "r", encoding="utf-8") as f:
                res["ctt_summary_precomputed"] = json.load(f)

        f_irt = os.path.join(cdir, "irt_summary.json")
        if os.path.exists(f_irt):
            with open(f_irt, "r", encoding="utf-8") as f:
                raw_irt = json.load(f)
                res["irt_summary_precomputed"] = {
                    tuple(k.split("___")): v for k, v in raw_irt.items()
                }

        f_sch_m = os.path.join(cdir, "school_by_mapel.parquet")
        if os.path.exists(f_sch_m):
            res["df_school_by_mapel"] = pd.read_parquet(f_sch_m)

        f_sch_c = os.path.join(cdir, "school_composite.parquet")
        if os.path.exists(f_sch_c):
            res["df_school_composite"] = pd.read_parquet(f_sch_c)

        f_prov = os.path.join(cdir, "region_prov.parquet")
        if os.path.exists(f_prov):
            res["region_prov_summary"] = pd.read_parquet(f_prov)

        f_kab = os.path.join(cdir, "region_kab.parquet")
        if os.path.exists(f_kab):
            res["region_kab_summary"] = pd.read_parquet(f_kab)

        f_geo = os.path.join(cdir, "geo_hierarchy.parquet")
        if os.path.exists(f_geo):
            res["geo_hierarchy"] = pd.read_parquet(f_geo)

    except Exception as e:
        print(f"Catatan muat cache analitik: {e}")

    return res


def precompute_and_save_all(
    df_peserta: pd.DataFrame,
    ctt_res: dict = None,
    scale_config: dict = None,
    mapel_lookup: dict = None,
) -> dict:
    """
    Menjalankan seluruh alur pra-komputasi analitik dan menyimpannya ke cache.
    Mengembalikan dictionary referensi untuk disuntikkan langsung ke st.session_state.
    """
    if df_peserta is None or df_peserta.empty:
        return {}

    ctt_dict = compute_ctt_precomputed(df_peserta, ctt_res, mapel_lookup)
    irt_dict = compute_irt_precomputed(df_peserta, scale_config)
    df_school_m, df_school_comp = compute_school_tables(df_peserta)
    df_prov_reg, df_kab_reg = compute_region_tables(df_peserta)
    df_geo_h = compute_geo_hierarchy(df_peserta)

    save_analytics_cache(
        ctt_dict=ctt_dict,
        irt_dict=irt_dict,
        df_school_m=df_school_m,
        df_school_comp=df_school_comp,
        df_prov_reg=df_prov_reg,
        df_kab_reg=df_kab_reg,
        df_geo_h=df_geo_h,
    )

    out = {
        "ctt_summary_precomputed": ctt_dict,
        "irt_summary_precomputed": irt_dict,
        "df_school_by_mapel": df_school_m,
        "df_school_composite": df_school_comp,
        "region_prov_summary": df_prov_reg,
        "region_kab_summary": df_kab_reg,
        "geo_hierarchy": df_geo_h,
    }

    # Set ke st.session_state
    for k, v in out.items():
        st.session_state[k] = v

    return out
