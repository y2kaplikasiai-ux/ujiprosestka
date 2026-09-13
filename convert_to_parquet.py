import glob
import time
import polars as pl

# Path folder dan pola nama file CSV Anda
# Contoh: Jika file-file CSV Anda ada di folder 'data_csv' dan bernama 'respon_1.csv', 'respon_2.csv', dll.
CSV_PATTERN = "data_csv/*.csv"  # <-- PASIKAN SESUAIKAN DENGAN FOLDER ANDA
OUTPUT_PARQUET = "data_respon_5juta.parquet"

def convert_csvs_to_parquet():
    print(f"🔍 Mencari file CSV dengan pola: {CSV_PATTERN}")
    files = glob.glob(CSV_PATTERN)
    print(f"📦 Ditemukan {len(files)} file CSV.")

    if not files:
        print("❌ File CSV tidak ditemukan! Periksa kembali path folder.")
        return

    t0 = time.time()
    print("⏳ Memulai penggabungan dan konversi streaming ke Parquet...")

    # Polars membaca seluruh file CSV secara Lazy (tanpa memakan RAM)
    lazy_df = pl.scan_csv(
        CSV_PATTERN,
        infer_schema_length=10000,
        ignore_errors=True
    )

    # Menuliskan langsung ke disk dalam format Parquet terkompresi
    lazy_df.sink_parquet(OUTPUT_PARQUET, compression="snappy")

    t1 = time.time()
    print(f"✅ Konversi selesai dalam {t1 - t0:.2f} detik!")
    print(f"📄 File hasil disimpan sebagai: {OUTPUT_PARQUET}")

if __name__ == "__main__":
    convert_csvs_to_parquet()