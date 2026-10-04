# validators.py
import csv
import io
import re
import pandas as pd


def clean_col(col):
    """Membersihkan nama kolom: menghapus spasi ekstra, mengubah ke lowercase,
    dan membuang karakter non-alphanumeric untuk pencocokan fleksibel.
    """
    if col is None:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(col).strip().lower())


KNOWN_MAPEL_FALLBACK = {
    "AMATW": "Matematika Wajib",
    "ABIGW": "Bahasa Inggris Wajib",
    "ABINW": "Bahasa Indonesia Wajib",
    "SEJ": "Sejarah",
    "EKO": "Ekonomi",
    "GEO": "Geografi",
    "SOS": "Sosiologi",
    "BIO": "Biologi",
    "FIS": "Fisika",
    "KIM": "Kimia",
    "MAT": "Matematika",
    "BIG": "Bahasa Inggris",
    "BIN": "Bahasa Indonesia",
}


def get_mapel_lookup_dict(df_mpl=None):
    """Mengekstrak kamus pemetaan kode_mapel -> nama_mapel dari DataFrame tabel master mapel."""
    lookup = dict(KNOWN_MAPEL_FALLBACK)
    if df_mpl is None or not isinstance(df_mpl, pd.DataFrame) or df_mpl.empty:
        return lookup

    cols = list(df_mpl.columns)
    col_kd = None
    for c in cols:
        clean = re.sub(r"[^a-z0-9]", "", str(c).lower())
        if clean in ["kodemapel", "kdmapel", "idmapel", "kodematapelajaran", "kd", "kode"]:
            col_kd = c
            break
    if not col_kd:
        for c in cols:
            low = str(c).lower()
            if ("kode" in low or "kd" in low or "id" in low) and "nama" not in low:
                col_kd = c
                break
    if not col_kd:
        col_kd = cols[0]

    col_nm = None
    for c in cols:
        if c == col_kd:
            continue
        clean = re.sub(r"[^a-z0-9]", "", str(c).lower())
        if clean in ["namamapel", "namamatapelajaran", "nama", "matapelajaran", "mapel"]:
            col_nm = c
            break
    if not col_nm:
        for c in cols:
            if c == col_kd:
                continue
            low = str(c).lower()
            if "nama" in low or "pelajaran" in low or (low == "mapel") or ("mapel" in low and "kode" not in low and "kd" not in low):
                col_nm = c
                break
    if not col_nm:
        other_cols = [c for c in cols if c != col_kd]
        if other_cols:
            col_nm = other_cols[0]

    if col_kd and col_nm and col_kd != col_nm:
        for _, row in df_mpl.iterrows():
            k_val = str(row[col_kd]).strip().upper()
            n_val = str(row[col_nm]).strip()
            if k_val and k_val not in ["NAN", "NONE", ""]:
                lookup[k_val] = n_val
                lookup[k_val.lower()] = n_val
    return lookup


def read_file_flexible(file_obj):
    """Membaca file CSV/Excel secara fleksibel atau mengembalikan DataFrame jika sudah dibaca."""
    if file_obj is None:
        return None

    # Jika objek yang masuk sudah merupakan DataFrame, langsung kembalikan
    if isinstance(file_obj, pd.DataFrame):
        return file_obj

    fname = getattr(file_obj, "name", "").lower()

    # 1. Jika File Excel (.xlsx, .xls)
    if fname.endswith((".xlsx", ".xls")):
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        return pd.read_excel(file_obj)

    # 2. Jika File CSV
    elif fname.endswith(".csv"):
        # Prioritas 1: Pembacaan Otomatis Engine Python Pandas (Paling stabil untuk CSV titik-koma)
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        try:
            df = pd.read_csv(
                file_obj,
                sep=None,
                engine="python",
                on_bad_lines="skip",
                encoding="utf-8",
            )
            # Pastikan kolom terpecah (lebih dari 1 kolom)
            if len(df.columns) > 1:
                return df
        except Exception:
            pass

        # Prioritas 2: Pakai Titik Koma (;) dengan UTF-8 (Sangat umum untuk data CSV sistem lokal ID/EU)
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        try:
            df = pd.read_csv(
                file_obj, sep=";", on_bad_lines="skip", encoding="utf-8"
            )
            if len(df.columns) > 1:
                return df
        except Exception:
            pass

        # Prioritas 3: csv.Sniffer sebagai alternatif jika cara 1 & 2 belum memecah kolom
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        try:
            sample = file_obj.read(20480)
            if isinstance(sample, bytes):
                sample = sample.decode("utf-8", errors="ignore")
            if hasattr(file_obj, "seek"):
                file_obj.seek(0)

            dialect = csv.Sniffer().sniff(sample, delimiters=[";", ",", "\t", "|"])
            df = pd.read_csv(
                file_obj, sep=dialect.delimiter, on_bad_lines="skip", encoding="utf-8"
            )
            if len(df.columns) > 1:
                return df
        except Exception:
            pass

        # Fallback 4: Titik koma (;) dengan encoding latin-1
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        try:
            df = pd.read_csv(
                file_obj, sep=";", on_bad_lines="skip", encoding="latin-1"
            )
            return df
        except Exception:
            pass

        # Fallback 5: Koma (,) dengan encoding latin-1
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        try:
            df = pd.read_csv(
                file_obj, sep=",", on_bad_lines="skip", encoding="latin-1"
            )
            return df
        except Exception:
            pass

    return pd.DataFrame()


def validate_7_files(uploaded_files):
    """Melakukan ingestion data dan validasi fleksibel untuk 7 berkas TKA."""
    logs = []
    dataframes = {}
    is_all_valid = True

    # Pemetaan alias variasi nama kolom wajib (dalam format bersih/lowercase)
    column_aliases = {
        "mapel": {
            "kode_mapel": [
                "kodemapel",
                "idmapel",
                "kdmapel",
                "kodematapelajaran",
            ],
            "nama_mapel": ["namamapel", "mapel", "namamatapelajaran"],
        },
        "respon": {
            "username": [
                "username",
                "usernames",
                "idpeserta",
                "id_peserta",
                "nisn",
                "id",
                "kodepeserta",
            ]
        },
        "kunci": {
            "kode_soal": ["kodesoal", "idsoal", "kdsoal", "nomorsoal", "nosoal", "kodepaket", "kode_paket", "paket"],
            "kunci_jawaban": ["kuncijawaban", "kunci", "jawaban", "kuncijawaban"],
        },
    }

    for file_key, file_obj in uploaded_files.items():
        if file_obj is not None:
            try:
                # Membaca DataFrame (bisa menerima DataFrame langsung atau file stream)
                df = read_file_flexible(file_obj)

                if df is None or df.empty:
                    logs.append(
                        f"❌ [ERROR] Berkas '{file_key}' kosong atau gagal dibaca."
                    )
                    is_all_valid = False
                    continue

                # Normalisasi seluruh nama kolom pada file yang dibaca
                col_map_clean = [clean_col(c) for c in df.columns]

                # Validasi ketersediaan kolom wajib jika ada aturan untuk file ini
                if file_key in column_aliases:
                    missing_cols = []
                    for req_col, aliases in column_aliases[file_key].items():
                        # Cek apakah nama kolom wajib / variasi aliasnya ada di file
                        found = any(alias in col_map_clean for alias in aliases)
                        if not found:
                            missing_cols.append(req_col)

                    if missing_cols:
                        logs.append(
                            f"❌ [ERROR] Berkas '{file_key}' kehilangan kolom wajib:"
                            f" {missing_cols}"
                        )
                        is_all_valid = False
                    else:
                        logs.append(
                            f"✅ [OK] Berkas '{file_key}' berhasil dimuat ({len(df):,} baris).".replace(",", ".")
                        )
                else:
                    logs.append(
                        f"✅ [OK] Berkas '{file_key}' berhasil dimuat ({len(df):,} baris).".replace(",", ".")
                    )

                # Ubah nama kolom DataFrame menjadi lowercase & hapus spasi agar aman di tahap pengolahan
                df.columns = [str(c).strip().lower() for c in df.columns]
                dataframes[file_key] = df

            except Exception as e:
                logs.append(f"❌ [ERROR] Gagal membaca berkas '{file_key}': {str(e)}")
                is_all_valid = False
        else:
            # Berkas selain respon & kunci bersifat opsional
            if file_key in ["respon", "kunci"]:
                logs.append(f"❌ [ERROR] Berkas Wajib '{file_key}' belum diunggah.")
                is_all_valid = False
            else:
                logs.append(f"⚠️ [INFO] Berkas Opsional '{file_key}' tidak diunggah.")
                dataframes[file_key] = None

    return {"status": is_all_valid, "logs": logs, "dataframes": dataframes}