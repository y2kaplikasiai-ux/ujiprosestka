import io
import pandas as pd


def export_analysis_to_excel(ctt_summary, irt_summary, equating_meta=None):
    """
    Mengekspor seluruh hasil analisis (CTT, IRT, dan Equating jika ada) ke format Excel (.xlsx).
    """
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Sheet 1: Hasil Analisis CTT
        if isinstance(ctt_summary, pd.DataFrame):
            ctt_summary.to_excel(writer, sheet_name="Analisis_CTT", index=False)
        elif isinstance(ctt_summary, dict):
            pd.DataFrame(ctt_summary).to_excel(writer, sheet_name="Analisis_CTT", index=False)
            
        # Sheet 2: Hasil Analisis IRT
        if isinstance(irt_summary, pd.DataFrame):
            irt_summary.to_excel(writer, sheet_name="Analisis_IRT", index=False)
        elif isinstance(irt_summary, dict):
            pd.DataFrame(irt_summary).to_excel(writer, sheet_name="Analisis_IRT", index=False)
            
        # Sheet 3: Hasil Equating
        if equating_meta and equating_meta.get("is_multi_session", False):
            rows = []
            base_sess = equating_meta.get("base_session", "")
            
            for sess_id, rep in equating_meta.get("reports", {}).items():
                if rep.get('status') == 'SUCCESS':
                    clean_warnings = " | ".join([
                        w.replace("**", "")
                         .replace("⚠️ ", "")
                         .replace("✅ ", "")
                         .replace("ℹ️ ", "")
                         .replace("❌ ", "")
                        for w in rep.get('warnings', [])
                    ])
                    rows.append({
                        "Sesi Target": f"Sesi {sess_id}",
                        "Sesi Acuan": f"Sesi {base_sess}",
                        "Jumlah Soal Jangkar": rep.get('n_anchor', 0),
                        "Rasio Jangkar (%)": round(rep.get('anchor_ratio', 0), 2),
                        "Korelasi Kesukaran (r)": round(rep.get('correlation', 0), 2),
                        "Konstanta A": round(rep.get('A', 1.0), 4),
                        "Konstanta B": round(rep.get('B', 0.0), 4),
                        "Catatan Psikometri": clean_warnings
                    })
                else:
                    rows.append({
                        "Sesi Target": f"Sesi {sess_id}",
                        "Sesi Acuan": f"Sesi {base_sess}",
                        "Jumlah Soal Jangkar": 0,
                        "Rasio Jangkar (%)": 0.0,
                        "Korelasi Kesukaran (r)": 0.0,
                        "Konstanta A": 1.0,
                        "Konstanta B": 0.0,
                        "Catatan Psikometri": rep.get('warnings', ["Gagal Equating"])[0] if rep.get('warnings') else "Gagal Equating"
                    })

            if rows:
                df_report = pd.DataFrame(rows)
                df_report.to_excel(writer, sheet_name="Hasil_Equating", index=False)
                
    output.seek(0)
    return output.getvalue()


def create_excel_report(df_matrix=None, df_ctt=None, df_irt=None, df_items=None, df_params=None, df_dist=None, df_persons_irt=None, equating_meta=None, **kwargs):
    """
    Fungsi fleksibel untuk membuat laporan Excel berdasarkan beberapa DataFrame hasil analisis.
    Mendukung penuh semua nama argumen dari app.py.
    """
    output = io.BytesIO()
    
    # Konsolidasi parameter
    ctt_data = df_ctt if df_ctt is not None else df_items
    irt_data = df_irt if df_irt is not None else df_params

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Sheet 1: Matrix / Data Respon Skor Dikotomus
        if df_matrix is not None and isinstance(df_matrix, pd.DataFrame):
            df_matrix.head(5000).to_excel(writer, sheet_name="Data_Matrix_Skor", index=False)

        # Sheet 2: CTT (Item Stats)
        if ctt_data is not None:
            if isinstance(ctt_data, pd.DataFrame):
                ctt_data.to_excel(writer, sheet_name="Analisis_CTT_Item", index=False)
            elif isinstance(ctt_data, dict):
                pd.DataFrame(ctt_data).to_excel(writer, sheet_name="Analisis_CTT_Item", index=False)

        # Sheet 3: Distractor Stats (Pengecoh)
        if df_dist is not None and isinstance(df_dist, pd.DataFrame):
            df_dist.to_excel(writer, sheet_name="Analisis_Pengecoh", index=False)

        # Sheet 4: IRT (Item Parameters)
        if irt_data is not None:
            if isinstance(irt_data, pd.DataFrame):
                irt_data.to_excel(writer, sheet_name="Parameter_Soal_IRT", index=False)
            elif isinstance(irt_data, dict):
                pd.DataFrame(irt_data).to_excel(writer, sheet_name="Parameter_Soal_IRT", index=False)

        # Sheet 5: IRT Person Abilities (Peserta)
        if df_persons_irt is not None and isinstance(df_persons_irt, pd.DataFrame):
            df_persons_irt.head(10000).to_excel(writer, sheet_name="Estimasi_Peserta_IRT", index=False)

        # Sheet 6: Hasil Equating Multi-Sesi
        if equating_meta and equating_meta.get("is_multi_session", False):
            rows = []
            base_sess = equating_meta.get("base_session", "")
            
            for sess_id, rep in equating_meta.get("reports", {}).items():
                if rep.get('status') == 'SUCCESS':
                    clean_warnings = " | ".join([
                        w.replace("**", "")
                         .replace("⚠️ ", "")
                         .replace("✅ ", "")
                         .replace("ℹ️ ", "")
                         .replace("❌ ", "")
                        for w in rep.get('warnings', [])
                    ])
                    rows.append({
                        "Sesi Target": f"Sesi {sess_id}",
                        "Sesi Acuan": f"Sesi {base_sess}",
                        "Jumlah Soal Jangkar": rep.get('n_anchor', 0),
                        "Rasio Jangkar (%)": round(rep.get('anchor_ratio', 0), 2),
                        "Korelasi Kesukaran (r)": round(rep.get('correlation', 0), 2),
                        "Konstanta A": round(rep.get('A', 1.0), 4),
                        "Konstanta B": round(rep.get('B', 0.0), 4),
                        "Catatan Psikometri": clean_warnings
                    })
                else:
                    rows.append({
                        "Sesi Target": f"Sesi {sess_id}",
                        "Sesi Acuan": f"Sesi {base_sess}",
                        "Jumlah Soal Jangkar": 0,
                        "Rasio Jangkar (%)": 0.0,
                        "Korelasi Kesukaran (r)": 0.0,
                        "Konstanta A": 1.0,
                        "Konstanta B": 0.0,
                        "Catatan Psikometri": rep.get('warnings', ["Gagal Equating"])[0] if rep.get('warnings') else "Gagal Equating"
                    })

            if rows:
                df_report = pd.DataFrame(rows)
                df_report.to_excel(writer, sheet_name="Hasil_Equating", index=False)

    output.seek(0)
    return output.getvalue()


def convert_df_to_csv_bytes(df: pd.DataFrame, delimiter: str = ';') -> bytes:
    """
    Mengonversi DataFrame pandas menjadi bytes berformat CSV.
    """
    output = io.BytesIO()
    df.to_csv(output, index=False, sep=delimiter, encoding='utf-8-sig')
    return output.getvalue()