from sqlalchemy import create_engine

# Format koneksi XAMPP standar (User: root, Password: "" [kosong], Host: localhost)
DATABASE_URL = "mysql+pymysql://root:@localhost:3306/db_psikometri"

try:
    engine = create_engine(DATABASE_URL)
    connection = engine.connect()
    print("✅ Berhasil terhubung ke database MySQL lokal!")
    connection.close()
except Exception as e:
    print("❌ Gagal terhubung ke database:", e)