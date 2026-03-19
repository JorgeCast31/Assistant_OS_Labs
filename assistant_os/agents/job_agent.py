"""
JobAgent - Simula búsqueda de vacantes de empleo.
Usa contratos Request/Response.
"""
from ..contracts import Request, Response, make_ok


class JobAgent:
    """Agente para búsqueda de empleos (stub)."""
    
    # Vacantes simuladas
    MOCK_JOBS = [
        {
            "title": "Senior Python Developer",
            "company": "TechCorp AI",
            "location": "Madrid, España",
            "remote": True,
            "url": "https://jobs.example.com/python-senior-001",
        },
        {
            "title": "Backend Engineer (Python/FastAPI)",
            "company": "StartupX",
            "location": "Barcelona, España",
            "remote": True,
            "url": "https://jobs.example.com/backend-fastapi-002",
        },
        {
            "title": "ML Engineer",
            "company": "DataVision Labs",
            "location": "Remote (EU)",
            "remote": True,
            "url": "https://jobs.example.com/ml-engineer-003",
        },
    ]
    
    def run(self, req: Request) -> Response:
        """
        Simula búsqueda de vacantes.
        
        Args:
            req: Request con payload.task
        
        Returns:
            Response estructurada
        """
        task = req["payload"].get("task", req["payload"].get("raw", ""))
        context_id = req["context_id"]
        
        return make_ok(
            agent="jobs",
            context_id=context_id,
            output={
                "results": self.MOCK_JOBS,
                "count": len(self.MOCK_JOBS),
                "query": task,
                "total_found": 47,
            },
        )
