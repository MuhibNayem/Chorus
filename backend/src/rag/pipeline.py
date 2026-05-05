import os
import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text:latest")


class EmbeddingService:
    def __init__(
        self,
        ollama_host: str = OLLAMA_HOST,
        model: str = OLLAMA_EMBEDDING_MODEL,
    ):
        self.ollama_host = ollama_host
        self.model = model

    async def embed_text(self, text: str) -> List[float]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.ollama_host}/api/embeddings",
                json={"model": self.model, "prompt": text},
            )
            response.raise_for_status()
            data = response.json()
            return data["embedding"]

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        embeddings = []
        async with httpx.AsyncClient(timeout=120.0) as client:
            for text in texts:
                response = await client.post(
                    f"{self.ollama_host}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                )
                response.raise_for_status()
                data = response.json()
                embeddings.append(data["embedding"])
        return embeddings


class RAGPipeline:
    def __init__(
        self,
        embedding_service: Optional[EmbeddingService] = None,
        database=None,
    ):
        self.embedding_service = embedding_service or EmbeddingService()
        self.database = database

    def set_database(self, database):
        self.database = database

    async def ingest_documents(
        self,
        source: str,
        documents: List[Dict[str, Any]],
        chunk_size: int = 512,
    ):
        if not self.database:
            raise ValueError("Database not set")

        for doc in documents:
            text = doc.get("text", "")
            metadata = doc.get("metadata", {})

            chunks = self._chunk_text(text, chunk_size)

            for i, chunk in enumerate(chunks):
                doc_id = await self.database.add_rag_document(
                    source=source,
                    chunk_text=chunk,
                    chunk_index=i,
                    metadata=metadata,
                )

                embedding = await self.embedding_service.embed_text(chunk)
                await self.database.add_rag_embedding(doc_id, embedding)

    def _chunk_text(self, text: str, chunk_size: int) -> List[str]:
        words = text.split()
        chunks = []
        for i in range(0, len(words), chunk_size):
            chunk = " ".join(words[i : i + chunk_size])
            chunks.append(chunk)
        return chunks

    async def retrieve_knowledge(
        self,
        query: str,
        top_k: int = 5,
        source_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not self.database:
            raise ValueError("Database not set")

        query_embedding = await self.embedding_service.embed_text(query)

        if source_filter:
            results = await self.database.search_rag_filtered(
                query_embedding, top_k, source_filter
            )
        else:
            results = await self.database.search_rag(query_embedding, top_k)

        return results

    async def get_context_for_query(self, query: str, top_k: int = 5) -> str:
        results = await self.retrieve_knowledge(query, top_k)

        if not results:
            return ""

        context_parts = []
        for result in results:
            context_parts.append(f"[{result['source']}]: {result['chunk_text']}")

        return "\n\n".join(context_parts)


KNOWLEDGE_BASE = {
    "spring_boot": [
        {
            "text": "Spring Boot 4 uses Java 21+ and introduces native compilation support via GraalVM. Key annotations include @SpringBootApplication, @RestController, @Service, @Repository, @Component for stereotyping. Use @Autowired for dependency injection, @Value for configuration, @ConfigurationProperties for type-safe configuration.",
            "metadata": {"category": "java", "framework": "spring-boot"},
        },
        {
            "text": "Spring Data JPA provides repository abstraction. Use JpaRepository<T, ID> for CRUD. @Entity, @Table, @Column for ORM mapping. @Id with @GeneratedValue for auto-increment. @Query for custom JPQL. @Transactional for atomic operations. Example: public interface UserRepository extends JpaRepository<User, Long> {}",
            "metadata": {"category": "java", "framework": "spring-data-jpa"},
        },
        {
            "text": "Spring Security 6+ uses component-based security. Configure SecurityFilterChain bean. @EnableWebSecurity for web security. Use formLogin(), httpBasic(), or JWT for authentication. CORS configuration via CorsConfiguration. Method-level security with @EnableMethodSecurity and @PreAuthorize.",
            "metadata": {"category": "java", "framework": "spring-security"},
        },
        {
            "text": "Spring Boot REST best practices: Use @RestController (not @Controller). Return ResponseEntity<T> for flexibility. Use DTOs, not entities in API. @Valid and BindingResult for validation. @ExceptionHandler for global error handling. Pagination with Pageable. Versioning via URL path or headers.",
            "metadata": {"category": "java", "framework": "rest"},
        },
    ],
    "svelte": [
        {
            "text": "Svelte 5 uses runes ($state, $derived, $effect) instead of stores. $state for reactive state: let count = $state(0). $derived for computed: let doubled = $derived(count * 2). $effect for side effects. Components use {#snippet} and {@render} for slots.",
            "metadata": {"category": "frontend", "framework": "svelte"},
        },
        {
            "text": "SvelteKit routing: +page.svelte for UI, +page.server.ts for server logic, +layout.svelte for shared UI. Use $page for current URL data. Form actions with <form method='POST'>. API routes in +server.ts files. Load function exports data to page.",
            "metadata": {"category": "frontend", "framework": "sveltekit"},
        },
        {
            "text": "Svelte 5 component props: let { name = 'default' } = $props(). Events use callback props: let { onClick } = $props(). Use event dispatcher for custom events. bind:this for DOM references. svelte:head for meta tags. svelte:window for window events.",
            "metadata": {"category": "frontend", "framework": "svelte"},
        },
    ],
    "architecture": [
        {
            "text": "Microservices communication: Synchronous via REST/gRPC, Asynchronous via message queues (Kafka, RabbitMQ). API Gateway pattern for unified entry point. Service discovery with Eureka or Consul. Circuit breaker with Resilience4j. Distributed tracing with Zipkin/Jaeger.",
            "metadata": {"category": "architecture", "topic": "microservices"},
        },
        {
            "text": "Clean Architecture layers: Domain (entities, value objects), Application (use cases, interfaces), Infrastructure (implementations, external services), Presentation (UI, API). Dependency rule: outer layers depend on inner layers, inner layers know nothing about outer.",
            "metadata": {"category": "architecture", "topic": "clean-architecture"},
        },
        {
            "text": "Authentication patterns: JWT with access/refresh tokens. OAuth2 for delegation. Session-based auth with HttpOnly cookies. Password hashing with bcrypt (cost factor 12+). MFA with TOTP. SSO with SAML/OIDC.",
            "metadata": {"category": "architecture", "topic": "security"},
        },
    ],
}


async def ingest_knowledge_base(rag_pipeline: RAGPipeline):
    for category, documents in KNOWLEDGE_BASE.items():
        await rag_pipeline.ingest_documents(
            source=f"knowledge_base/{category}",
            documents=documents,
        )
