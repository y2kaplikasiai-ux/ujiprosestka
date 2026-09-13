import pymysql

# Koneksi ke server MySQL tanpa memilih database terlebih dahulu
connection = pymysql.connect(
    host='localhost',
    user='root',
    password=''  # Password standar XAMPP biasanya kosong
)

try:
    with connection.cursor() as cursor:
        # Buat database jika belum ada
        cursor.execute("CREATE DATABASE IF NOT EXISTS db_psikometri;")
        print("✅ Database 'db_psikometri' berhasil dibuat/tersedia!")
finally:
    connection.close()