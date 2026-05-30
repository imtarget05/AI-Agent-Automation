# 📋 MULTI-AGENT PLATFORM ENGINEERING: MASTER TO-DO LIST & ROADMAP

Bản kế hoạch hành động và danh sách công việc (To-Do List) này được thiết lập để định hình dự án của bạn thành một hệ thống **AI-powered Platform Engineering**: **Multi-Agent AIOps + RAG + DevOps Automation + Observability + Guardrails** đạt tiêu chuẩn vận hành thực tế (Production-Grade).

---

## 🗺️ LỘ TRÌNH TRIỂN KHAI TỔNG THỂ (PHASED ROADMAP)

Chúng ta sẽ tập trung hoàn thiện dự án theo **3 Giai đoạn (Phases)**, đi từ nền tảng chạy vững chắc đến mở rộng tích hợp hệ thống công cụ và cuối cùng là bảo mật, đo lường chuẩn hóa:

```
┌─────────────────────────────────┐      ┌──────────────────────────────────┐      ┌─────────────────────────────────┐
│     PHASE 1 — NỀN TẢNG CORE     │ ───> │   PHASE 2 — AGENT GỌI TOOL THẬT  │ ───> │  PHASE 3 — PRODUCTION HARDENING │
│  Gateway, LangGraph, RAG, DBs   │      │  MCP, K8s, Prometheus, incident  │      │  Guardrails, Tracing, Evals, OT │
└─────────────────────────────────┘      └──────────────────────────────────┘      └─────────────────────────────────┘
```

---

## 🛠️ CHI TIẾT CÁC BƯỚC THỰC HIỆN & DANH SÁCH CÔNG VIỆC

---

### 🟢 PHASE 1: NỀN TẢNG CORE CHẠY ĐƯỢC (P0 - Ưu tiên hàng đầu)
*Mục tiêu: Xây dựng bộ khung gầm gồm API Gateway, bộ điều phối trung tâm LangGraph, cơ chế Memory (Redis/Qdrant) và công cụ RAG cơ bản để chat với tài liệu repo.*

#### 1.1 Khởi tạo cấu trúc Thư mục & Môi trường
- [x] **1.1.1 Cập nhật cấu trúc thư mục platform**:
  Tổ chức lại monorepo theo đúng cấu trúc đề xuất:
  ```
  apps/gateway/            # Cổng API chính
  apps/social/             # Webhook Facebook/Zalo
  apps/browser/            # Web automation (Playwright)
  apps/computer_use/       # Desktop automation (Xvfb)
  shared/                  # Config, LLM Router, DB Memory chung
  docs/                    # Tài liệu kiến trúc & hạ tầng
  ```
- [x] **1.1.2 Tích hợp hạ tầng Docker Compose**:
  - [x] Tích hợp PostgreSQL (Cơ sở dữ liệu chính).
  - [x] Tích hợp Redis (Message Broker & Cache).
  - [x] Tích hợp Qdrant (Vector DB).
  - [x] Tích hợp **Ollama** (Local LLM chạy DeepSeek-R1:8b).
  - [x] Tích hợp **n8n** (Visual Orchestrator).
- [x] **1.1.3 Thiết lập cấu hình hệ thống (`.env` & `shared/config.py`)**:
  - [x] Tạo file `.env` mẫu đầy đủ cổng kết nối Postgres, Redis, Qdrant, Ollama, n8n.
  - [x] Khai báo các mô hình sử dụng (`DEFAULT_MODEL`, `FALLBACK_MODEL`).

#### 1.2 Hoàn thiện API Gateway & Bộ định tuyến LangGraph
- [x] **1.2.1 Hoàn thiện Router Thông minh (`shared/llm.py`)**:
  - [x] Nâng cấp class `LLMRouter` hỗ trợ kết nối `ollama` cục bộ và cloud APIs song song.
  - [x] Bật cơ chế cost-aware routing (chọn model rẻ cho tác vụ phân tích, model đắt cho tác vụ code).
- [x] **1.2.2 Wire-up (Nối cáp) Gateway và các Sub-Agents (`apps/gateway/orchestrator.py`)**:
  - [x] Loại bỏ hoàn toàn Mock/Placeholder trong các Node LangGraph (`_browser_node`, `_computer_use_node`).
  - [x] Thay thế bằng các cuộc gọi HTTP (`httpx`) bất đồng bộ sang container `browser:8003` và `computer_use:8004`.
- [x] **1.2.3 Xây dựng Session Memory (`shared/memory.py`)**:
  - [x] Hoàn thiện class `SessionMemory` lưu conversation history vào Redis dưới định dạng ChatMessage với TTL 24h.
  - [x] Thiết lập `LongTermMemory` kết nối Qdrant để lưu trữ ngữ nghĩa bộ nhớ dài hạn của user.

#### 1.3 Triển khai RAG Service & Tri thức hệ thống (`services/rag-service`)
- [x] **1.3.1 Ingestion Pipeline (Nạp tài liệu)**:
  - [x] Viết script tự động đọc tài liệu định dạng Markdown, PDF, LaTeX trong thư mục `docs/` và `README.md`.
  - [x] Thực hiện Chunking (cắt nhỏ văn bản) và nhúng (Embedding) sử dụng mô hình local của Ollama hoặc OpenAI.
- [x] **1.3.2 Retrieval API (Truy vấn tri thức)**:
  - [x] Viết API `/retrieve` để lấy ra Top-K tài liệu liên quan nhất đến lỗi hệ thống hoặc hướng dẫn vận hành (Runbook).

---

### 🟡 PHASE 2: AGENT GỌI TOOL THẬT (P1 - Mở rộng năng lực)
*Mục tiêu: Đưa các Agent chuyên biệt vào hoạt động. Kết nối Agent với hệ thống tool thật như Kubernetes (K8s), Prometheus, Logs hệ thống và Git.*

#### 2.1 Xây dựng Tool Registry & Expose APIs (`tools/`)
Để Agent không gây lỗi bảo mật, toàn bộ các công cụ (Tools) phải được đóng gói thành các dịch vụ API chuẩn hóa hoặc tích hợp giao thức **MCP (Model Context Protocol)**:
- [ ] **2.1.1 `k8s-tool`**: Expose các API an toàn: `get_pods`, `get_logs`, `get_events`, `describe_pod`. Ngăn chặn việc xóa/sửa nếu không có quyền Admin.
- [ ] **2.1.2 `prometheus-tool`**: API tiếp nhận câu lệnh PromQL, truy vấn tài nguyên CPU/RAM, lỗi hệ thống hoặc latency của các service mục tiêu.
- [ ] **2.1.3 `log-tool`**: Trình tìm kiếm và lọc logs nâng cao từ file log hệ thống hoặc các hệ thống lưu trữ tập trung.
- [ ] **2.1.4 `github-tool` / `git-tool`**: Tự động hóa việc đọc Git diff, tạo pull request (PR) commit sửa lỗi hoặc tạo GitHub Issue để theo dõi incident.
- [x] **2.1.5 `email-tool`**: Tool cấp thấp để gửi email, tạo nháp, đính kèm báo cáo sự cố qua SMTP / Gmail API / SendGrid / AWS SES (Priority P1).

#### 2.2 Wire-up Bộ Agent AIOps cốt lõi (`agents/`)
- [ ] **2.2.1 `aiops-agent` (Agent phát hiện sự cố)**:
  - [ ] Nhận dữ liệu Alert từ Prometheus hoặc Event Bus.
  - [ ] Tự động tóm tắt tình trạng lỗi hệ thống (Anomaly Summary) gửi về Gateway.
- [ ] **2.2.2 `rca-agent` (Agent phân tích nguyên nhân gốc)**:
  - [ ] Khi có sự cố, tự động gọi `prometheus-tool` and `log-tool` để so khớp.
  - [ ] Lập biểu đồ nguyên nhân (Root Cause) kèm bằng chứng (Logs/Metrics cụ thể).
- [ ] **2.2.3 `rag-agent` (Agent tài liệu & Runbook)**:
  - [ ] Gọi `rag-service` để truy vấn xem sự cố này đã có trong tài liệu hướng dẫn xử lý sự cố (Runbook) hay chưa.
  - [ ] Trích xuất các bước đề xuất xử lý sự cố chuẩn.
- [ ] **2.2.4 `devops-agent` (Agent đề xuất và thực thi sửa lỗi)**:
  - [ ] Viết code đề xuất sửa lỗi (ví dụ: vá file cấu hình K8s `.yaml`, sửa Dockerfile hoặc code bị bug).
  - [ ] Tự động đẩy đề xuất sửa lỗi lên GitHub dưới dạng PR.
- [x] **2.2.5 `email-agent`**: Agent soạn nội dung email báo cáo incident, email xin approval, tóm tắt lỗi hệ thống gửi stakeholder, cho phép chọn tone giọng (formal, short summary...) (Priority P1).

---

### 🔴 PHASE 3: PRODUCTION HARDENING (P2 - An toàn & Vận hành chuyên nghiệp)
*Mục tiêu: Đảm bảo Agent vận hành an toàn trong môi trường doanh nghiệp. Kiểm soát hành vi nguy hiểm, đo lường độ chính xác và giám sát toàn diện.*

#### 3.1 Hệ thống An toàn & Giám sát Tác vụ (Safety & Guardrails)
- [x] **3.1.1 Triển khai `guardrail-service`**:
  - [x] **Input Guardrail**: Quét prompt đầu vào của người dùng chống Prompt Injection (nhồi lệnh độc hại).
  - [x] **Tool Guardrail**: Kiểm soát chặt chẽ các công cụ có tính phá hủy (ví dụ: Lệnh Shell, scale down pod K8s).
  - [x] Thiết lập cơ chế **Human-in-the-loop (Chờ con người phê duyệt)** thông qua cổng Gateway trước khi Agent thực thi các tool có độ rủi ro cao.

#### 3.2 Hệ thống Đánh giá Chất lượng & Tracing (Tracing & Evals)
- [ ] **3.2.1 Triển khai `trace-service`**:
  - [ ] Tích hợp **LangSmith** hoặc **Langfuse** (Open-source) thông qua biến môi trường để vẽ toàn bộ bản đồ cây thực thi LLM, xem rõ Agent nào gọi Tool nào, thời gian xử lý bao lâu.
- [ ] **3.2.2 Triển khai `eval-service`**:
  - [ ] Xây dựng bộ dataset test (`data/evals/`) gồm các câu hỏi mẫu và kết quả mong đợi.
  - [ ] Chạy tự động đánh giá độ chính xác (Accuracy, Hallucination) của Agent mỗi khi cập nhật Prompt hoặc nâng cấp Model LLM.

#### 3.3 Hệ thống Giám sát Hệ điều hành (Observability Stack)
- [ ] **3.3.1 Tích hợp Prometheus & Grafana Dashboards**:
  - [ ] Collect metrics về hiệu suất của hệ thống: Tần suất gọi LLM, Token cost hàng tháng, thời gian phản hồi API Gateway, số lượng tác vụ trong hàng đợi.
  - [ ] Thiết kế giao diện Dashboard Grafana chuyên biệt giám sát AI Agent.

---

## 🎭 KỊCH BẢN DEMO THỰC TẾ (DEMO FLOW STORYBOARD)

Để chứng minh giá trị của hệ thống **Multi-Agent AIOps Platform**, kịch bản demo đỉnh cao dưới đây cần được thực hiện thành công:

```
[Prometheus Alert: CPU Pod K8s vượt 95%]
                │
                ▼ (Event Bus nhận tín hiệu)
[aiops-agent]: Phát hiện cảnh báo anomaly -> Tạo Incident ID: INC-102
                │
                ▼ (Gọi RCA Agent)
[rca-agent]: Gọi `k8s-tool` lấy logs + `prometheus-tool` phân tích -> Phát hiện rò rỉ bộ nhớ (Memory Leak) ở service web
                │
                ▼ (Gọi RAG Agent)
[rag-agent]: Gọi `rag-service` tra cứu Runbook -> Tìm thấy tài liệu xử lý sự cố Memory Leak
                │
                ▼ (Gọi DevOps Agent)
[devops-agent]: Tạo file patch K8s YAML -> Đẩy code lên GitHub PR
                │
                ▼ (Gọi Report Agent)
[report-agent]: Tạo báo cáo incident (Incident Report) chi tiết dạng Markdown
                │
                ▼ (Gọi Email Agent)
[email-agent]: Soạn nội dung email dễ hiểu (chọn non-tech tone gửi stakeholder, formal tone gửi admin)
                │
                ▼ (Kích hoạt Guardrail)
[guardrail-service]: Quét kiểm tra an toàn nội dung email và lệnh deployment
                │
                ▼ (Human Approval)
[Gateway / n8n]: Admin nhấn nút "APPROVE" duyệt rollout và đồng ý gửi báo cáo email
                │
                ▼ (Thực thi & Gửi đi)
[email-tool]: Gọi SMTP/SendGrid gửi email báo cáo đính kèm incident report đến stakeholder
[slack-tool]: Gửi thông báo hoàn thành sự cố kèm link PR và tóm tắt qua Slack!
```

---

## 📈 DANH SÁCH SERVICES MVP ĐỂ COMMIT LÊN REPO

| Nhóm chức năng | Tên Service | Trạng thái tích hợp | File cấu hình liên quan | Priority |
| :--- | :--- | :--- | :--- | :--- |
| **API & Gateway** | `api-gateway` | ✅ Đã có khung core | `apps/gateway/main.py` | P0 |
| **Orchestrator** | `agent-orchestrator` | ✅ Hoàn thành (Real HTTP Calls) | `apps/gateway/orchestrator.py` | P0 |
| **Vector DB** | `qdrant` | ✅ Đã tích hợp Docker | `docker-compose.yml` | P0 |
| **Local LLM** | `ollama` | ✅ Đã tích hợp Docker | `docker-compose.yml`, `.env` | P0 |
| **Workflow UI** | `n8n` | ✅ Đã tích hợp Docker | `docker-compose.yml` | P0 |
| **Database & Cache** | `postgres`, `redis` | ✅ Đã tích hợp Docker | `docker-compose.yml` | P0 |
| **RAG System** | `rag-service` | ✅ Hoàn thành (Cổng 8007) | `services/rag_service/main.py` | P0 |
| **AIOps Agents** | `aiops-agent`, `rca-agent` | ⏳ Phase 2 (Chờ làm) | `agents/` | P0 |
| **DevOps Agents** | `devops-agent` | ⏳ Phase 2 (Chờ làm) | `agents/` | P0 |
| **Email Agent** | `email-agent` | ✅ Hoàn thành (Cổng 8009) | `apps/email_agent/main.py` | P1 |
| **Email Tool** | `email-tool` | ✅ Hoàn thành (Cổng 8008) | `tools/email.py` | P1 |
| **Approval System** | `approval-service` | ⏳ Phase 3 (Chờ làm) | `services/approval-service/` | P1 |
| **Safety & Eval** | `guardrail-service` | ✅ Hoàn thành (Cổng 8010) | `services/guardrail_service/main.py` | P0 |

---

*To-Do List này sẽ đóng vai trò là "Kim chỉ nam" kỹ thuật giúp bạn từng bước hiện thực hóa nền tảng Platform Engineering mạnh mẽ của mình!*
