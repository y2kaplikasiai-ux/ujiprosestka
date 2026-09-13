# ui_components.py
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def render_score_histogram(df_matrix):
    """Menampilkan histogram distribusi nilai konversi (skala 0 - 100)."""
    df = df_matrix.copy()

    # Deteksi kolom nilai konversi
    target_col = None
    for col in df.columns:
        if col.lower() in [
            "nilai_konversi",
            "nilaikonversi",
            "nilai_persen",
            "nilai",
        ]:
            target_col = col
            break

    if target_col is None:
        # Jika tidak ada, cari skor mentah
        for col in df.columns:
            if col.lower() in ["skor_mentah", "skor_total", "skormentah", "skor"]:
                target_col = col
                break

    if target_col is None:
        target_col = df.columns[-1]

    # Proteksi Tambahan: Jika nilai maksimal <= 1, kalikan 100
    if df[target_col].max() <= 1.0:
        df[target_col] = df[target_col] * 100

    fig = px.histogram(
        df,
        x=target_col,
        nbins=20,
        title="Distribusi Nilai Konversi Peserta (Skala 0 - 100)",
        labels={target_col: "Nilai Konversi"},
        color_discrete_sequence=["#2b5c8f"],
    )

    fig.update_layout(
        xaxis_title="Nilai Konversi",
        yaxis_title="Jumlah Peserta",
        template="plotly_white",
        margin=dict(l=20, r=20, t=40, b=20),
        bargap=0.05,
    )
    return fig


def render_ctt_scatter(df_items, p_col, r_col):
    """Menampilkan Scatter Plot CTT: Tingkat Kesukaran (p) vs Daya Beda (r)."""
    fig = px.scatter(
        df_items,
        x=p_col,
        y=r_col,
        hover_data=[df_items.columns[0]],
        title="Scatter Plot CTT: Tingkat Kesukaran vs Daya Beda",
        labels={
            p_col: "Tingkat Kesukaran (p-value)",
            r_col: "Daya Beda (Point Biserial / r)",
        },
        color_discrete_sequence=["#1f77b4"],
    )

    # Garis Panduan / Threshold Standard
    fig.add_hline(
        y=0.2, line_dash="dash", line_color="red", annotation_text="Batas Min DB (0.2)"
    )
    fig.add_vline(
        x=0.3,
        line_dash="dot",
        line_color="orange",
        annotation_text="Sukar (<0.3)",
    )
    fig.add_vline(
        x=0.7,
        line_dash="dot",
        line_color="green",
        annotation_text="Mudah (>0.7)",
    )

    fig.update_layout(
        template="plotly_white", margin=dict(l=20, r=20, t=40, b=20)
    )
    return fig


def render_irt_icc(df_params, selected_items, model_type, b_col):
    """Menampilkan Curve Characteristic Item (ICC) untuk IRT."""
    fig = go.Figure()
    if df_params is None or df_params.empty or not selected_items:
        return fig

    theta = np.linspace(-4, 4, 200)

    # Cari kolom daya beda (a) dan tebakan semu (c) jika ada
    a_cols = [
        c
        for c in df_params.columns
        if c.lower() in ["a", "daya_beda", "discrimination", "a_param"]
    ]
    c_cols = [
        c
        for c in df_params.columns
        if c.lower() in ["c", "tebakan", "guessing", "c_param", "pseudo_guessing"]
    ]
    
    a_col = a_cols[0] if len(a_cols) > 0 else None
    c_col = c_cols[0] if len(c_cols) > 0 else None

    item_id_col = df_params.columns[0]

    for item in selected_items:
        row = df_params[df_params[item_id_col].astype(str) == str(item)]
        if row.empty:
            continue

        # Extract b & validasi nilai None/NaN
        raw_b = row[b_col].values[0] if b_col in row.columns else 0.0
        b = float(raw_b) if pd.notna(raw_b) else 0.0

        # Extract a (untuk model 2PL dan 3PL)
        a = 1.0
        if model_type.upper() in ["2PL", "3PL"] and a_col and a_col in row.columns:
            raw_a = row[a_col].values[0]
            a = float(raw_a) if pd.notna(raw_a) else 1.0

        # Extract c (untuk model 3PL)
        c = 0.0
        if model_type.upper() == "3PL" and c_col and c_col in row.columns:
            raw_c = row[c_col].values[0]
            c = float(raw_c) if pd.notna(raw_c) else 0.0

        # Formula Logistik IRT 3PL / 2PL / 1PL / Rasch yang aman
        exp_val = np.exp(np.clip(-a * (theta - b), -100, 100))
        p_theta = c + (1.0 - c) / (1.0 + exp_val)

        fig.add_trace(
            go.Scatter(
                x=theta,
                y=p_theta,
                mode="lines",
                name=f"Soal {item} (b={b:.2f})",
            )
        )

    fig.update_layout(
        title=f"Item Characteristic Curves (ICC) - Model {model_type}",
        xaxis_title="Kemampuan Peserta (Theta θ)",
        yaxis_title="Peluang Menjawab Benar P(θ)",
        template="plotly_white",
        yaxis=dict(range=[0, 1.05]),
        margin=dict(l=20, r=20, t=40, b=20),
    )
    return fig


def render_irt_tif(df_params, model_type, b_col):
    """Menampilkan Test Information Function (TIF) & SEM."""
    fig = go.Figure()
    if df_params is None or df_params.empty or b_col not in df_params.columns:
        return fig

    theta = np.linspace(-4, 4, 200)
    a_cols = [
        c
        for c in df_params.columns
        if c.lower() in ["a", "daya_beda", "discrimination", "a_param"]
    ]
    c_cols = [
        c
        for c in df_params.columns
        if c.lower() in ["c", "tebakan", "guessing", "c_param", "pseudo_guessing"]
    ]
    
    a_col = a_cols[0] if len(a_cols) > 0 else None
    c_col = c_cols[0] if len(c_cols) > 0 else None

    tif = np.zeros_like(theta)

    for _, row in df_params.iterrows():
        raw_b = row[b_col]
        b = float(raw_b) if pd.notna(raw_b) else 0.0

        a = 1.0
        if model_type.upper() in ["2PL", "3PL"] and a_col and a_col in row.index:
            raw_a = row[a_col]
            a = float(raw_a) if pd.notna(raw_a) else 1.0

        c = 0.0
        if model_type.upper() == "3PL" and c_col and c_col in row.index:
            raw_c = row[c_col]
            c = float(raw_c) if pd.notna(raw_c) else 0.0

        exp_val = np.exp(np.clip(-a * (theta - b), -100, 100))
        p = c + (1.0 - c) / (1.0 + exp_val)
        q = 1.0 - p

        # Item Information Function
        if model_type.upper() == "3PL" and c > 0:
            i_theta = (a**2) * (q / p) * (((p - c) / (1 - c)) ** 2)
        else:
            i_theta = (a**2) * p * q

        tif += np.nan_to_num(i_theta)

    # Standard Error of Measurement (SEM) = 1 / sqrt(TIF)
    sem = np.where(tif > 0.0001, 1 / np.sqrt(tif), np.nan)

    fig.add_trace(
        go.Scatter(
            x=theta,
            y=tif,
            mode="lines",
            name="Fungsi Informasi (TIF)",
            line=dict(color="blue", width=2),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=theta,
            y=sem,
            mode="lines",
            name="Standard Error (SEM)",
            line=dict(color="red", width=2, dash="dash"),
        )
    )

    fig.update_layout(
        title="Test Information Function (TIF) & Standard Error (SEM)",
        xaxis_title="Kemampuan Peserta (Theta θ)",
        yaxis_title="Informasi / SE",
        template="plotly_white",
        margin=dict(l=20, r=20, t=40, b=20),
    )
    return fig


def render_wright_map(df_persons, df_params, theta_col, b_col):
    """Menampilkan Wright Map (Person-Item Map)."""
    fig = go.Figure()

    persons_theta = []
    if df_persons is not None and theta_col and theta_col in df_persons.columns:
        persons_theta = df_persons[theta_col].dropna().values

    items_b = []
    if df_params is not None and b_col and b_col in df_params.columns:
        items_b = df_params[b_col].dropna().values

    fig.add_trace(
        go.Box(
            y=persons_theta,
            name="Sebaran Peserta (Theta)",
            boxpoints="all",
            jitter=0.3,
            pointpos=-1.8,
            marker_color="mediumseagreen",
        )
    )

    fig.add_trace(
        go.Box(
            y=items_b,
            name="Tingkat Kesukaran Soal (b)",
            boxpoints="all",
            jitter=0.3,
            pointpos=-1.8,
            marker_color="coral",
        )
    )

    fig.update_layout(
        title="Wright Map (Peta Distribusi Peserta & Soal)",
        yaxis_title="Skala Logit (Theta / Kesukaran)",
        template="plotly_white",
        margin=dict(l=20, r=20, t=40, b=20),
    )
    return fig