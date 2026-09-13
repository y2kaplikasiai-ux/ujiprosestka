import numpy as np
import pandas as pd
import streamlit as st

# Impor fungsi IRT dari modul irt_analysis
try:
    from irt_analysis import run_irt_analysis
except ImportError:
    run_irt_analysis = None


@st.cache_data
def run_cached_session_irt(df_sub_matrix, model_type):
    """
    Menjalankan analisis IRT per sesi dengan caching Streamlit.
    Hasil komputasi tersimpan di RAM sehingga tidak dihitung ulang saat reload/pindah tab.
    """
    if run_irt_analysis is None:
        raise ImportError("Fungsi run_irt_analysis tidak dapat diimpor dari irt_analysis.py")
    return run_irt_analysis(df_sub_matrix, model_type=model_type)


def check_anchor_quality(anchor_b_base, anchor_b_target, total_items_target):
    """
    Memeriksa kelayakan psikometri dari soal jangkar dan mengembalikan daftar catatan/warning.
    """
    warnings = []
    n_anchor = len(anchor_b_base)
    anchor_ratio = (n_anchor / total_items_target) * 100 if total_items_target > 0 else 0
    
    # 1. Cek kecukupan jumlah anchor (10-20%)
    if anchor_ratio < 10:
        warnings.append(
            f"⚠️ **Jumlah Soal Jangkar Kurang**: Ditemukan {n_anchor} soal jangkar ({anchor_ratio:.1f}% dari total {total_items_target} soal target). "
            f"Idealnya minimal 10-20% dari total soal. Hasil equating berisiko kurang stabil."
        )
    elif 10 <= anchor_ratio <= 30:
        warnings.append(
            f"✅ **Jumlah Soal Jangkar Ideal**: Ditemukan {n_anchor} soal jangkar ({anchor_ratio:.1f}% dari total {total_items_target} soal target)."
        )
    else:
        warnings.append(
            f"ℹ️ **Catatan**: Jumlah soal jangkar cukup tinggi ({anchor_ratio:.1f}%). Sangat baik untuk stabilitas equating."
        )
        
    # 2. Cek korelasi parameter kesukaran (b) antar-sesi
    corr = 0.0
    if n_anchor >= 3:
        corr = np.corrcoef(anchor_b_base, anchor_b_target)[0, 1]
        if np.isnan(corr):
            corr = 0.0
            
        if corr < 0.80:
            warnings.append(
                f"⚠️ **Korelasi Anchor Rendah**: Korelasi kesukaran soal jangkar r = {corr:.2f} (Ideal: >= 0.80). "
                f"Indikasi ada soal jangkar yang karakteristiknya berubah atau bocor."
            )
        else:
            warnings.append(
                f"✅ **Korelasi Anchor Baik**: Korelasi kesukaran soal jangkar r = {corr:.2f}."
            )
    elif n_anchor > 0:
        warnings.append(
            "⚠️ **Soal Jangkar Terlalu Sedikit**: Tidak cukup data untuk menghitung korelasi parameter kesukaran (minimal 3 butir)."
        )
            
    return warnings, anchor_ratio, corr


def mean_sigma_equating(anchor_b_base, anchor_b_target):
    """
    Menghitung konstanta transformasi Mean-Sigma (A dan B).
    A = SD(b_target) / SD(b_base)
    B = Mean(b_target) - A * Mean(b_base)
    """
    mean_base = np.mean(anchor_b_base)
    mean_target = np.mean(anchor_b_target)
    
    sd_base = np.std(anchor_b_base, ddof=1) if len(anchor_b_base) > 1 else 0
    sd_target = np.std(anchor_b_target, ddof=1) if len(anchor_b_target) > 1 else 0
    
    if sd_base == 0 or np.isnan(sd_base):
        A = 1.0
    else:
        A = sd_target / sd_base
        
    B = mean_target - (A * mean_base)
    return A, B


def _extract_irt_components(sess_data):
    """
    Helper fleksibel untuk mengonversi output IRT (baik berbentuk DataFrame maupun Dict)
    menjadi dictionary parameter b, a, dan array/Series theta.
    """
    b_dict = {}
    a_dict = None
    theta_vals = None

    if isinstance(sess_data, dict):
        # 1. Ekstrak parameter 'b' dan 'a' dari item_params (jika bertingkat)
        if "item_params" in sess_data and isinstance(sess_data["item_params"], pd.DataFrame):
            df_item = sess_data["item_params"]
            col_item = df_item.columns[0]
            b_col = next((c for c in df_item.columns if c.lower().strip() in ["b", "kesukaran", "difficulty", "b_param"]), None)
            if not b_col:
                b_col = df_item.columns[1] if len(df_item.columns) > 1 else None
            
            if b_col and b_col in df_item.columns:
                b_dict = dict(zip(df_item[col_item].astype(str), df_item[b_col]))
                
            a_col = next((c for c in df_item.columns if c.lower().strip() in ["a", "daya_beda", "discrimination"]), None)
            if a_col and a_col in df_item.columns:
                a_dict = dict(zip(df_item[col_item].astype(str), df_item[a_col]))

        elif "b" in sess_data:
            b_dict = sess_data["b"]
            if isinstance(sess_data.get("a"), dict):
                a_dict = sess_data["a"]

        # 2. Ekstrak parameter 'theta' dari person_params
        if "person_params" in sess_data and isinstance(sess_data["person_params"], pd.DataFrame):
            df_person = sess_data["person_params"]
            t_col = next((c for c in df_person.columns if c.lower() in ["kemampuan (theta θ)", "theta", "theta_ability", "ability", "skor_theta"]), None)
            if not t_col:
                numeric_cols = df_person.select_dtypes(include=[np.number]).columns
                t_col = numeric_cols[0] if len(numeric_cols) > 0 else df_person.columns[0]
            theta_vals = df_person[t_col].values
        elif "theta" in sess_data:
            theta_vals = sess_data["theta"]

    return b_dict, a_dict, theta_vals


def perform_multi_session_equating(df_responses, session_irt_results, base_session_id=1):
    """
    Fungsi utama untuk memproses equating multi-sesi otomatis.
    """
    col_sesi = next(
        (c for c in df_responses.columns if c.lower().strip() in ["kode_sesi", "kodesesi", "sesi", "session_id", "session"]),
        None
    )
    
    if not col_sesi or col_sesi not in df_responses.columns:
        return None, {"is_multi_session": False, "message": "Kolom 'kode_sesi' tidak ditemukan pada data respon."}

    unique_sessions = sorted(df_responses[col_sesi].dropna().unique())
    
    # Jika hanya ada 1 sesi, kembalikan data asli tanpa perubahan
    if len(unique_sessions) <= 1:
        return None, {"is_multi_session": False, "message": "Hanya 1 sesi terdeteksi. Equating tidak diperlukan."}
    
    equated_results = {}
    equating_reports = {}
    
    # Pastikan sesi acuan ada di daftar sesi
    if base_session_id not in unique_sessions:
        base_session_id = unique_sessions[0]
        
    base_b_dict, base_a_dict, base_theta = _extract_irt_components(session_irt_results[base_session_id])
    
    for sess_id in unique_sessions:
        if sess_id not in session_irt_results:
            continue

        target_b_dict, target_a_dict, target_theta = _extract_irt_components(session_irt_results[sess_id])

        # Sesi acuan tidak perlu ditransformasi (A=1, B=0)
        if sess_id == base_session_id:
            equated_results[sess_id] = {
                'b': base_b_dict.copy(),
                'a': base_a_dict.copy() if base_a_dict is not None else None,
                'theta': base_theta.copy() if base_theta is not None else np.array([])
            }
            continue
            
        # Deteksi otomatis soal jangkar (intersection kode_soal)
        anchor_items = list(set(base_b_dict.keys()).intersection(set(target_b_dict.keys())))
        
        if len(anchor_items) == 0:
            equating_reports[sess_id] = {
                'status': 'FAILED',
                'n_anchor': 0,
                'anchor_ratio': 0.0,
                'correlation': 0.0,
                'A': 1.0,
                'B': 0.0,
                'warnings': [f"❌ **Error Equating Sesi {sess_id}**: Tidak ditemukan soal jangkar yang sama dengan Sesi {base_session_id}."]
            }
            equated_results[sess_id] = session_irt_results[sess_id]
            continue
            
        anchor_b_base = [base_b_dict[item] for item in anchor_items]
        anchor_b_target = [target_b_dict[item] for item in anchor_items]
        
        total_items_target = len(target_b_dict)
        warnings, ratio, corr = check_anchor_quality(anchor_b_base, anchor_b_target, total_items_target)
        
        # Hitung A dan B
        A, B = mean_sigma_equating(anchor_b_base, anchor_b_target)
        
        # Transformasi parameter b & a
        b_equated = {item: (A * b_val + B) for item, b_val in target_b_dict.items()}
        a_equated = None
        if target_a_dict is not None:
            a_equated = {item: (a_val / A if A != 0 else a_val) for item, a_val in target_a_dict.items()}
            
        # Transformasi theta peserta
        theta_equated = None
        if target_theta is not None:
            theta_equated = A * target_theta + B
        
        equated_results[sess_id] = {
            'b': b_equated,
            'a': a_equated,
            'theta': theta_equated
        }
        
        equating_reports[sess_id] = {
            'status': 'SUCCESS',
            'n_anchor': len(anchor_items),
            'anchor_ratio': ratio,
            'correlation': corr,
            'A': A,
            'B': B,
            'warnings': warnings
        }
        
    return equated_results, {"is_multi_session": True, "reports": equating_reports, "base_session": base_session_id}