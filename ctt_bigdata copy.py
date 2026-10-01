import time
import polars as pl


def run_ctt_analysis_5m(parquet_path: str, id_col: str):
  """Menghitung CTT untuk 5 Juta Peserta menggunakan Polars Streaming Engine."""
  t0 = time.time()
  print("⚡ Menjalankan Analisis CTT Streaming...")

  # 1. Scan file Parquet
  q = pl.scan_parquet(parquet_path)

  # 2. Ambil daftar kolom soal (semua kolom kecuali ID)
  schema = q.collect_schema()
  all_cols = schema.names()
  item_cols = [c for c in all_cols if c != id_col]
  k_soal = len(item_cols)

  print(f"📊 Jumlah Soal Terdeteksi: {k_soal}")

  # 3. Hitung Total Skor per Peserta & Statistik Total
  q_with_score = q.with_columns(
      pl.sum_horizontal(item_cols).alias("Skor_Total")
  )

  # Expressi Agregasi P-Value (Mean) dan Varians Soal
  stats_exprs = []
  for col in item_cols:
    stats_exprs.append(pl.col(col).mean().alias(f"{col}_pvalue"))
    stats_exprs.append(pl.col(col).var().alias(f"{col}_var"))

  # 4. Eksekusi Agregasi Statistik Item secara Streaming (Hemat RAM)
  item_stats_df = q.select(stats_exprs).collect(streaming=True)

  # 5. Hitung Varians Skor Total & Metadata
  total_stats = q_with_score.select([
      pl.col("Skor_Total").var().alias("var_total"),
      pl.col("Skor_Total").count().alias("n_peserta"),
      pl.col("Skor_Total").mean().alias("mean_skor"),
  ]).collect(streaming=True)

  var_total = total_stats["var_total"][0]
  n_peserta = total_stats["n_peserta"][0]
  mean_skor = total_stats["mean_skor"][0]

  # 6. Hitung Cronbach's Alpha (Keandalan Tes)
  sum_item_vars = sum([item_stats_df[f"{col}_var"][0] for col in item_cols])
  cronbach_alpha = (
      (k_soal / (k_soal - 1)) * (1 - (sum_item_vars / var_total))
      if var_total > 0
      else 0.0
  )

  # 7. Susun Hasil Statistik Soal menjadi Dataframe
  items_summary = []
  for col in item_cols:
    items_summary.append({
        "Kode_Soal": col,
        "Tingkat_Kesukaran_P": round(item_stats_df[f"{col}_pvalue"][0], 3),
        "Varians_Item": round(item_stats_df[f"{col}_var"][0], 3),
    })

  df_result_items = pl.DataFrame(items_summary)
  t1 = time.time()

  print(f"✅ Analisis Selesai dalam {t1 - t0:.2f} detik!")

  return {
      "summary": {
          "n_peserta": n_peserta,
          "n_soal": k_soal,
          "cronbach_alpha": round(cronbach_alpha, 3),
          "mean_skor": round(mean_skor, 2),
      },
      "item_stats": df_result_items,
  }


# --- UJI COBA EKSEKUSI ---
if __name__ == "__main__":
  file_parquet = "data_respon_5juta_combined.parquet"
  nama_kolom_id = "id_peserta"  # Ubah sesuai nama kolom ID di file kamu

  hasil = run_ctt_analysis_5m(file_parquet, id_col=nama_kolom_id)

  print("\n=== RINGKASAN HASIL ===")
  print(f"Total Peserta    : {hasil['summary']['n_peserta']:,}")
  print(f"Total Soal       : {hasil['summary']['n_soal']}")
  print(f"Cronbach's Alpha : {hasil['summary']['cronbach_alpha']}")
  print(f"Rata-rata Skor   : {hasil['summary']['mean_skor']}")
  print("\n10 Soal Pertama:")
  print(hasil["item_stats"].head(10))