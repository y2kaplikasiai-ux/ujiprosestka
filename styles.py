import streamlit as st

def load_custom_css():
    """
    Memuat CSS custom untuk merapikan layout sidebar,
    menghilangkan teks limit ukuran file tanpa mengganggu tombol upload.
    """
    st.markdown("""
        <style>
        /* Import Font Inter */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        
        html, body, [class*="css"] {
            font-family: 'Inter', sans-serif;
        }

        /* 1. Header Utama Dashboard */
        .main-header {
            font-size: 1.8rem;
            font-weight: 700;
            margin-bottom: 0.2rem;
        }
        .sub-header {
            font-size: 0.9rem;
            opacity: 0.8;
            margin-bottom: 1rem;
        }

        /* 2. Informasi Format di Paling Atas Sidebar */
        .info-header-box {
            background-color: rgba(37, 99, 235, 0.15);
            border: 1px solid rgba(37, 99, 235, 0.4);
            border-radius: 6px;
            padding: 6px 10px;
            margin-bottom: 12px;
            font-size: 0.75rem;
            text-align: center;
        }

        /* 3. Label Nama File / Kotak Upload */
        .upload-label-container {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-top: 6px;
            margin-bottom: 2px;
        }

        .upload-label-title {
            font-size: 0.82rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .upload-label-badge {
            background-color: #2563EB;
            color: #FFFFFF !important;
            font-size: 0.65rem;
            font-weight: 700;
            border-radius: 4px;
            padding: 1px 6px;
        }

        .upload-label-file {
            font-size: 0.72rem;
            opacity: 0.7;
            font-family: monospace;
        }

        /* -------------------------------------------------------------
           PENYESUAIAN FILE UPLOADER (PURE CSS - TANPA SCRIPT JS)
        ------------------------------------------------------------- */
        
        /* Ringkaskan area dropzone */
        section[data-testid="stSidebar"] [data-testid="stFileUploader"] section {
            padding: 6px !important;
            min-height: unset !important;
            border-radius: 6px !important;
        }

        /* Sembunyikan elemen instruksi teks "200MB per file..." saja secara presisi */
        section[data-testid="stSidebar"] [data-testid="stFileUploader"] [data-testid="stFileUploadDropzoneInstructions"],
        section[data-testid="stSidebar"] [data-testid="stFileUploader"] section > div > div > small,
        section[data-testid="stSidebar"] [data-testid="stFileUploader"] section > div > div > span {
            display: none !important;
            visibility: hidden !important;
            height: 0px !important;
            margin: 0 !important;
            padding: 0 !important;
        }

        /* Lindungi tombol upload dan teks di dalamnya agar TETAP MUNCUL BERSIH */
        section[data-testid="stSidebar"] [data-testid="stFileUploader"] button {
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            padding: 4px 16px !important;
            font-size: 0.8rem !important;
            height: auto !important;
            min-height: 32px !important;
            border-radius: 6px !important;
            margin: 0 auto !important;
            visibility: visible !important;
            opacity: 1 !important;
        }

        section[data-testid="stSidebar"] [data-testid="stFileUploader"] button * {
            display: inline-block !important;
            visibility: visible !important;
            opacity: 1 !important;
            font-size: 0.8rem !important;
        }
        </style>
    """, unsafe_allow_html=True)