web: uvicorn api.ingest_endpoints:app --host 0.0.0.0 --port $PORT
dashboard: streamlit run dashboard/main.py --server.port $PORT --server.address 0.0.0.0