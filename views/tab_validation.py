import streamlit as st


def render_tab_validation(val_result):
    """
    Render Tab 1: Validasi Data / Status Pemrosesan.
    
    - Jika data SUDAH diproses (data_processed == True):
      Menampilkan kontainer status pengolahan data selesai beserta langkah per langkah (1/6 s.d. 6/6).
    - Jika data BELUM diproses:
      Menampilkan hasil pemeriksaan Ingestion Data awal dan peninjauan tabel.
    """
    is_processed = st.session_state.get("data_processed", False)

    if is_processed:
        # --- TAMPILAN JIKA PROSES DATA SUDAH SELESAI ---
        total_time_str = st.session_state.get("total_process_time_str", "00:00:00")
        total_time_sec = st.session_state.get("total_process_time_sec", 0.0)
        process_logs = st.session_state.get("process_logs", [])

        with st.container(border=True):
            st.markdown(
                f"✔️ 🎉 **Pengolahan Data Selesai dalam {total_time_str}** ({total_time_sec:.2f} dtk)!"
            )
            st.progress(1.0)

            st.write("")  # Spasi pemisah

            for log in process_logs:
                step_num = log.get("step_num", 1)
                total_steps = log.get("total_steps", 6)
                name = log.get("name", "")
                dur = log.get("dur", 0.0)

                st.markdown(
                    f"✅ **Langkah {step_num}/{total_steps}:** {name} *(selesai dalam ` {dur:.2f} dtk `)*"
                )
    else:
        # --- TAMPILAN JIKA BELUM DIPROSES (Hasil Pemeriksaan Ingestion Data) ---
        st.subheader("Hasil Pemeriksaan Ingestion Data")
        
        if val_result and "logs" in val_result:
            for log in val_result["logs"]:
                if "❌" in log:
                    st.error(log)
                elif "⚠️" in log:
                    st.warning(log)
                elif "---" in log:
                    st.markdown(f"**{log}**")
                else:
                    st.success(log)

            if val_result.get("status", False):
                st.success("🎉 Data berhasil divalidasi dan siap untuk diproses!")
                st.divider()
                
                if "dataframes" in val_result and val_result["dataframes"]:
                    preview_key = st.selectbox(
                        "Pilih Tabel untuk Ditinjau:", list(val_result["dataframes"].keys())
                    )
                    if (
                        preview_key in val_result["dataframes"]
                        and val_result["dataframes"][preview_key] is not None
                    ):
                        df_preview = val_result["dataframes"][preview_key].head(10).copy()
                        df_preview = df_preview.loc[:, ~df_preview.columns.duplicated()]
                        df_preview.insert(0, "No.", range(1, 1 + len(df_preview)))
                        st.dataframe(df_preview, use_container_width=True, hide_index=True)
        else:
            st.info("Silakan unggah berkas dan klik **🚀 Proses Data** untuk memulai.")