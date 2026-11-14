"""Corpus definition: three Vietnamese laws taken from the official Công báo PDFs."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
BENCHMARK_DIR = REPO_ROOT / "benchmark"
RESULTS_DIR = REPO_ROOT / "results"

LICENSE_NOTE = (
    "Văn bản quy phạm pháp luật, không thuộc phạm vi bảo hộ quyền tác giả "
    "(Điều 15 Luật Sở hữu trí tuệ); bản PDF lấy nguyên trạng từ Công báo Chính phủ."
)

DOCUMENTS = [
    {
        "document_id": "luat-anm-2025",
        "file": "luat-116-2025-qh15-anm.pdf",
        "title": "Luật An ninh mạng",
        "law_number": "116/2025/QH15",
        "gazette": "Công báo số 35 ngày 21-01-2026",
        "url": "https://congbaocdn.chinhphu.vn/180507251028987904/2026/1/23/116signed-1769163678477753319408.pdf",
        "landing_page": "https://congbao.chinhphu.vn/van-ban/luat-so-116-2025-qh15-468678.htm",
    },
    {
        "document_id": "luat-gddt-2023",
        "file": "luat-20-2023-qh15-gddt.pdf",
        "title": "Luật Giao dịch điện tử",
        "law_number": "20/2023/QH15",
        "gazette": "Công báo số 867 + 868 ngày 30-7-2023",
        "url": "https://datafiles.chinhphu.vn/cpp/files/vbpq/2023/8/luat20-2023-qh15..pdf",
        "landing_page": "https://vanban.chinhphu.vn/?docid=208421&pageid=27160",
    },
    {
        "document_id": "luat-bvdlcn-2025",
        "file": "luat-91-2025-qh15-bvdlcn.pdf",
        "title": "Luật Bảo vệ dữ liệu cá nhân",
        "law_number": "91/2025/QH15",
        "gazette": "Công báo số 971 + 972 ngày 24-7-2025",
        "url": "https://congbaocdn.chinhphu.vn/CongBaoCP/VanBan/2025/6/45578/57730-1-2025971-97291-2025-qh15.pdf",
        "landing_page": "https://congbao.chinhphu.vn/van-ban/luat-so-91-2025-qh15-45578.htm",
    },
]
