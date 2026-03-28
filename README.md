# report_system

An intelligent report generation system that combines AI-powered analysis with a skill-based architecture. The system integrates knowledge graph retrieval (Neo4j), semantic search (FAISS), and a multi-step agent workflow to generate structured analytical reports through an interactive web interface (Vue 3 + FastAPI).

## Key Features
- Agentic orchestration using the ReAct pattern with modular skills
- Knowledge graph and semantic retrieval for context-aware report generation
- Interactive frontend with real-time streaming and outline editing
- Extensible skill system (skill-factory, outline-generate, data-execute, report-generate, etc.)