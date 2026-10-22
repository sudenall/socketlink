# SocketLink Project Report Template & Skeleton

> **Owner:** Nevin Malkoç (Report Coordinator & Editor)  
> **Target Document:** Google Docs (Single unified document)  
> **Format Rules:** Times New Roman, 12 pt (headings: 14 pt bold uppercase), 1.5 line spacing, margins: Left 4 cm, Right 1.5 cm, Top/Bottom 2.5 cm, justified alignment, IEEE referencing style (README §12).

---

## Cover Page
- **Course Name / Code:** Computer Networks / Socket Programming Term Project
- **Project Title:** SocketLink: A Dual-Transport (TCP & Reliable UDP) Multi-Client Chat and File Transfer System with Live Network Simulation
- **Team Members & Student IDs:**
  1. Sude (Team Leader & Protocol Architect)
  2. Nevin Malkoç (Documentation & High-Level Network Diagrams)
  3. Yusuf (Concurrent Server Architecture)
  4. Hamit (Client Core & Fault Tolerance)
  5. Yiğit (Reliable UDP Transport & ARQ Protocol)
  6. İlayda (Client Graphical User Interface)
  7. Tina (Server Dashboard & File Transfer Subsystem)
  8. Meryem (Verification, Testing & Benchmarking)
- **Submission Date:** Phase 1 / Final Term 2026

---

## Executive Abstract [Nevin]
*(To be completed in final review: ~250-300 words summarizing problem statement, dual-transport design pattern, Go-Back-N implementation, and quantitative performance under simulated packet loss).*

---

## List of Figures
- **Figure 3.1:** Top-Level Network Architecture Diagram (HLD-1)
- **Figure 3.2:** Detailed Network and Concurrency Architecture Diagram (HLD-2)
- **Figure 3.3:** Packet Structure and Reliable UDP Go-Back-N Retransmission Sequence (HLD-3)
- **Figure 4.1:** Client and Server Graphical User Interface Dashboards
- **Figure 4.2:** Throughput and Latency Metrics Across Packet Loss Rates (0% - 30%)

---

## List of Tables
- **Table 1.1:** Feasibility Comparison: Protocol and Architecture Trade-offs
- **Table 2.1:** Literature Review Matrix on Networked Systems and Transport Reliability
- **Table 3.1:** SocketLink Fixed 22-Byte Binary Header Specification
- **Table 3.2:** Event Data Contracts in the Observer Architecture
- **Table 3.3:** Rubric Requirements to Report Section Mapping (Part #1 & Part #2)

---

## List of Abbreviations
| Abbreviation | Definition |
|---|---|
| ACK | Acknowledgement |
| API | Application Programming Interface |
| ARQ | Automatic Repeat reQuest |
| CRC | Cyclic Redundancy Check |
| FIFO | First-In, First-Out |
| GBN | Go-Back-N |
| GUI | Graphical User Interface |
| HLD | High-Level Design |
| IP | Internet Protocol |
| LAN | Local Area Network |
| OS | Operating System |
| RTT | Round-Trip Time |
| TCP | Transmission Control Protocol |
| UDP | User Datagram Protocol |
| UI | User Interface |

---

## Rubric Mapping Table (Requirements Compliance)

| Rubric Code | Category | Requirement Description | Report Section | Owner | Points |
|---|---|---|---|---|---|
| **FS-1** | Feasibility Study | Project Scope | Section 1.6 | Sude | 2 |
| **FS-2** | Feasibility Study | Objectives of the project design network | Section 1.5 | Sude | 3 |
| **FS-3** | Feasibility Study | Intended Users | Section 1.2 | İlayda | 2 |
| **FS-4** | Feasibility Study | Design Assumptions | Section 1.6 | Yusuf | 3 |
| **FS-5** | Feasibility Study | Strategy Justification & Alternative Evaluation | Section 1.7 | Sude | 5 |
| **FS-6** | Feasibility Study | Industry/Business Domain Overview | Section 1.3 | Yiğit | 3 |
| **FS-7** | Feasibility Study | Problem, Domain Rules & Constraints | Section 1.4 | Hamit | 2 |
| **NNA-1**| Needs Analysis | Data Types in Design Network | Section 3.6.1 | Tina | 2 |
| **NNA-2**| Needs Analysis | Data Sources | Section 3.6.2 | Tina | 3 |
| **NNA-3**| Needs Analysis | Number of Users & Priority Levels | Section 3.6.3 | Yusuf | 2 |
| **NNA-4**| Needs Analysis | Transmission Speed Requirements | Section 3.6.4 | Yusuf | 3 |
| **NNA-5**| Needs Analysis | Storage Requirements | Section 3.6.5 | Tina | 2 |
| **NNA-6**| Needs Analysis | Reliability Requirements | Section 3.6.6 | Hamit | 3 |
| **NNA-7**| Needs Analysis | Security Requirements | Section 3.6.7 | Hamit | 2 |
| **NNA-8**| Needs Analysis | Architecture, Components & Interaction | Section 3.6.8 | Sude | 3 |
| **HLD-1**| High-Level Design | Top-Level Network Diagram | Section 3.6.9 | Nevin | 5 |
| **HLD-2**| High-Level Design | Detailed Network Diagram | Section 3.6.10 | Nevin | 5 |
| **HLD-3**| High-Level Design | Detailed Network Sub-Diagram | Section 3.6.11 | Nevin | 5 |
| **HLD-4**| High-Level Design | Integration & Functional Composition | Section 3.6.12 | İlayda | 5 |
| **DDD-1**| Detailed Design | Advantages & Disadvantages of Chosen Solution | Section 3.11 | Sude + Yusuf | 5 |
| **DDD-2**| Detailed Design | Testing & Verification Assessment Strategy | Section 4.2 | Meryem | 5 |
| **Part #2**| Implementation | Complete GUI Program & Live Simulation | Section 4.1 & Code | Team | 30 |

---

## Chapter 1: Introduction and Feasibility Study
*(Sections 1.1 - 1.8 authored by respective section owners according to REPORT_GUIDE.md)*

---

## Chapter 2: Literature Review
*(Peer-reviewed citations from 2014 onwards. 3 articles per team member).*

### 2.8 Client-Server Architecture Modelling & Network Socket Abstractions [Nevin]
1. **[Gorton2015]** I. Gorton, *Essential Software Architecture*, 2nd ed. Berlin, Germany: Springer, 2015, pp. 45–68. DOI: 10.1007/978-3-642-19176-3.
   - *Summary:* Discusses structural decomposition of distributed systems, thread-per-request concurrency bottlenecks, and decoupling presentation from transport layers.
   - *Application to SocketLink:* Validates the selection of thread-per-client server model up to 50 concurrent connections and reinforces clean separation between Tkinter UI and network threads via an asynchronous EventBus.
2. **[Fall2011]** K. R. Fall and W. R. Stevens, *TCP/IP Illustrated, Volume 1: The Protocols*, 2nd ed. Boston, MA: Addison-Wesley, 2011, ch. 1–3, 10.
   - *Summary:* Provides rigorous foundations for framing, stream-oriented vs datagram-oriented transport, and sliding window flow control semantics.
   - *Application to SocketLink:* Dictated the fixed 22-byte binary header design and cumulative acknowledgement mechanism in the reliable UDP transport layer.
3. **[Papadopoulos2016]** A. V. Papadopoulos, M. Verscheure, D. Terragno, and A. Leva, "Model-based control of networked server architectures," *IEEE Transactions on Control Systems Technology*, vol. 24, no. 4, pp. 1361–1373, Jul. 2016. DOI: 10.1109/TCST.2015.2497318.
   - *Summary:* Analyzes latency variance, queue buildup, and stability under stochastic packet transmission delays in networked multi-client systems.
   - *Application to SocketLink:* Informs the simulation testbed for evaluating Go-Back-N retransmission delays and buffer limits under simulated packet loss.

---

## Chapter 3: System Design and High-Level Architecture

### 3.6.9 Top-Level Network Diagram (HLD-1) [Nevin]
*(Refers to Figure 3.1 from `docs/diagrams/fig-3-6-9-top-level.drawio`).*  
Explains the topological interconnection between distributed clients running the Tkinter interface, the routing network with simulated degradation, and the centralized SocketLink server binding on port 5050.

### 3.6.10 Detailed Network Diagram (HLD-2) [Nevin]
*(Refers to Figure 3.2 from `docs/diagrams/fig-3-6-10-detailed.drawio`).*  
Details process boundaries, thread allocation (`srv-accept`, `ClientHandler`, `cli-receiver`, `cli-heartbeat`), thread-safe event queuing, and modular decoupling between Transport, Core, and Presentation tiers.

### 3.6.11 Detailed Network Sub-Diagram (HLD-3) [Nevin]
*(Refers to Figure 3.3 from `docs/diagrams/fig-3-6-11-sub-diagram.drawio`).*  
Presents the exact binary byte-layout of the 22-byte header followed by the Go-Back-N sequence timeline demonstrating cumulative ACKs, duplicate ACKs on out-of-order delivery, and retransmission timeout recovery.

---

## Chapter 5: Conclusion, Future Research Works, and Remarks [Nevin]
*(Summary of architectural outcomes, lessons learned from socket programming concurrency, and future extensions including TLS encryption and Selective Repeat ARQ).*

---

## References (IEEE Format)
*(Consolidated bibliography maintained by Nevin).*
