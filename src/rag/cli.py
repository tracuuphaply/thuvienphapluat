import argparse
import logging
from pathlib import Path
from src.config import DATA_DIR
from src.rag.db_rag import RAGDatabase
from src.rag.rag_indexer import index_from_phase1
from src.rag.hybrid_search import hybrid_search
from src.rag.report_generator import generate_compliance_report
from src.rag.graph_traversal import impact_analysis
from src.rag.embeddings_api import EmbeddingAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="RAG CLI for thuvienphapluat")
    subparsers = parser.add_subparsers(dest="command")
    
    parser_index = subparsers.add_parser("index")
    parser_index.add_argument("--force", action="store_true", help="Force re-index")
    parser_index.add_argument("--stats", action="store_true", help="Print stats only")
    
    parser_search = subparsers.add_parser("search")
    parser_search.add_argument("query", type=str)
    parser_search.add_argument("--limit", type=int, default=10)
    
    parser_report = subparsers.add_parser("report")
    parser_report.add_argument("industry", type=str)
    parser_report.add_argument("--days", type=int, default=250)
    parser_report.add_argument("--pdf", action="store_true", help="Also export as PDF file")
    
    parser_impact = subparsers.add_parser("impact")
    parser_impact.add_argument("doc_num", type=str)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return

    rag_db_path = DATA_DIR / "rag.db"
    rag_db = RAGDatabase(rag_db_path)
    
    if args.command == "index":
        # Pass a dummy path for Phase 1 db_path because index_from_phase1 uses get_session() which relies on config
        index_from_phase1(DATA_DIR / "legal_docs.db", rag_db, force=args.force, stats_only=args.stats)
    elif args.command == "search":
        embedder = EmbeddingAPI()
        results = hybrid_search(rag_db, args.query, embedder=embedder, limit=args.limit)
        for r in results:
            print(f"[{r.final_score:.4f}] {r.doc_num} - {r.heading}")
    elif args.command == "report":
        report = generate_compliance_report(rag_db, args.industry, days=args.days)
        print(report)
        if args.pdf:
            from src.utils.pdf_exporter import convert_md_to_pdf
            pdf_path = convert_md_to_pdf(report, report_title=f"BÁO CÁO PHÁP LÝ CHUYÊN ĐỀ — NGÀNH {args.industry.upper()}")
            print(f"\n✅ Đã xuất file PDF thành công tại: {pdf_path}")

    elif args.command == "impact":
        affected = impact_analysis(rag_db, args.doc_num)
        print(f"Impact Analysis for {args.doc_num}:")
        for a in affected:
            print(f"- {a.doc_num} ({a.relation})")
            
    rag_db.close()

if __name__ == "__main__":
    main()
