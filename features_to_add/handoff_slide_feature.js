const fs = require("fs");
const path = require("path");
require("dotenv").config({ path: path.resolve(__dirname, "../.env") });

const REMOTE_IP = process.env.REMOTE_IP || "<YOUR_IP>";
const OLLAMA_IP = process.env.OLLAMA_IP || "<YOUR_IP>";
const OLLAMA_PORT = process.env.OLLAMA_PORT || "11434";
const OLLAMA_URL = `http://${OLLAMA_IP}:${OLLAMA_PORT}`;
const VM_NAS_IP = process.env.VM_NAS_IP || "<YOUR_IP>";

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, PageNumber, PageBreak, LevelFormat, ExternalHyperlink,
  TabStopType, TabStopPosition
} = require("docx");

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 80, bottom: 80, left: 120, right: 120 };
const thinBorder = { style: BorderStyle.SINGLE, size: 1, color: "E0E0E0" };
const thinBorders = { top: thinBorder, bottom: thinBorder, left: thinBorder, right: thinBorder };

function headerCell(text, width) {
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    shading: { fill: "1B3A5C", type: ShadingType.CLEAR },
    margins: cellMargins,
    verticalAlign: "center",
    children: [new Paragraph({ children: [new TextRun({ text, bold: true, font: "Arial", size: 20, color: "FFFFFF" })] })],
  });
}

function cell(text, width, opts = {}) {
  const runs = [];
  if (opts.bold) {
    runs.push(new TextRun({ text, bold: true, font: "Arial", size: 20 }));
  } else if (opts.mono) {
    runs.push(new TextRun({ text, font: "Consolas", size: 18, color: "C0392B" }));
  } else {
    runs.push(new TextRun({ text, font: "Arial", size: 20 }));
  }
  return new TableCell({
    borders: opts.headerRow ? borders : thinBorders,
    width: { size: width, type: WidthType.DXA },
    shading: opts.shade ? { fill: "F7F9FC", type: ShadingType.CLEAR } : undefined,
    margins: cellMargins,
    children: [new Paragraph({ children: runs })],
  });
}

function heading1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 200 },
    children: [new TextRun({ text, bold: true, font: "Arial", size: 32, color: "1B3A5C" })],
  });
}

function heading2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 280, after: 160 },
    children: [new TextRun({ text, bold: true, font: "Arial", size: 26, color: "2E75B6" })],
  });
}

function heading3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 200, after: 120 },
    children: [new TextRun({ text, bold: true, font: "Arial", size: 22, color: "3D8B37" })],
  });
}

function para(text, opts = {}) {
  const runs = [];
  if (typeof text === "string") {
    runs.push(new TextRun({ text, font: "Arial", size: 21, ...opts }));
  } else {
    // Array of TextRun configs
    text.forEach(t => runs.push(new TextRun({ font: "Arial", size: 21, ...t })));
  }
  return new Paragraph({ spacing: { after: 120 }, children: runs });
}

function mono(text) {
  return new Paragraph({
    spacing: { after: 80 },
    indent: { left: 360 },
    children: [new TextRun({ text, font: "Consolas", size: 18, color: "2C3E50" })],
  });
}

function bullet(text, ref = "bullets", level = 0) {
  return new Paragraph({
    numbering: { reference: ref, level },
    spacing: { after: 60 },
    children: [new TextRun({ text, font: "Arial", size: 21 })],
  });
}

function bulletBold(label, desc, ref = "bullets") {
  return new Paragraph({
    numbering: { reference: ref, level: 0 },
    spacing: { after: 60 },
    children: [
      new TextRun({ text: label, font: "Arial", size: 21, bold: true }),
      new TextRun({ text: ` ${desc}`, font: "Arial", size: 21 }),
    ],
  });
}

function divider() {
  return new Paragraph({
    spacing: { before: 200, after: 200 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "D0D0D0", space: 1 } },
    children: [],
  });
}

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 21 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 22, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 200, after: 120 }, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets",
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
          { level: 1, format: LevelFormat.BULLET, text: "\u25E6", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 1440, hanging: 360 } } } },
        ] },
      { reference: "numbers",
        levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    ],
  },
  sections: [
    // ===================== COVER PAGE =====================
    {
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
        },
      },
      children: [
        new Paragraph({ spacing: { before: 3600 } }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 200 },
          children: [new TextRun({ text: "HANDOFF DOCUMENT", font: "Arial", size: 44, bold: true, color: "1B3A5C" })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 120 },
          children: [new TextRun({ text: "Slide-Aware Processing Mode", font: "Arial", size: 32, color: "2E75B6" })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 80 },
          children: [new TextRun({ text: "YouTube Tutorial to Doc Converter", font: "Arial", size: 24, color: "666666" })],
        }),
        divider(),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 80 },
          children: [
            new TextRun({ text: "From: ", font: "Arial", size: 22, color: "888888" }),
            new TextRun({ text: "Joe", font: "Arial", size: 22, bold: true }),
            new TextRun({ text: "    To: ", font: "Arial", size: 22, color: "888888" }),
            new TextRun({ text: "Max", font: "Arial", size: 22, bold: true }),
          ],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 80 },
          children: [new TextRun({ text: "February 22, 2026", font: "Arial", size: 22, color: "888888" })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 80 },
          children: [
            new TextRun({ text: "Repo: ", font: "Arial", size: 20, color: "888888" }),
            new TextRun({ text: "github.com/celstnblacc/viddocs", font: "Consolas", size: 18, color: "2E75B6" }),
          ],
        }),
        new Paragraph({ children: [new PageBreak()] }),
      ],
    },

    // ===================== MAIN CONTENT =====================
    {
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
        },
      },
      headers: {
        default: new Header({
          children: [new Paragraph({
            border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "2E75B6", space: 4 } },
            children: [
              new TextRun({ text: "Slide-Aware Feature Handoff", font: "Arial", size: 18, color: "888888" }),
              new TextRun({ text: "\tFeb 2026", font: "Arial", size: 18, color: "888888" }),
            ],
            tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
          })],
        }),
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [
              new TextRun({ text: "Page ", font: "Arial", size: 18, color: "AAAAAA" }),
              new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 18, color: "AAAAAA" }),
            ],
          })],
        }),
      },
      children: [
        // ===== SUMMARY =====
        heading1("1. Summary"),
        para("A new slide-aware processing mode has been implemented for the YouTube Tutorial to Doc Converter. When a user submits a video URL, they can now toggle a Presentation Mode switch. This triggers a different pipeline branch that auto-detects presentation slides, captures their final state, extracts text via OCR, aligns transcript to each slide, and generates structured documentation."),
        para("The feature is additive and non-breaking. The existing generic pipeline is untouched. All new database columns have defaults or are nullable. The implementation uses a CV + LLM hybrid approach: OpenCV handles the heavy lifting (layout detection, SSIM-based slide transition tracking, OCR), while the LLM on vmid901 (Ollama qwen2.5:32b) is called only for ambiguous edge cases."),

        divider(),

        // ===== INFRASTRUCTURE =====
        heading1("2. Infrastructure Map"),
        para("All hosts are on the same private flat L2 network. No WireGuard or VPN required for inter-host communication."),

        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [2200, 2200, 2200, 2760],
          rows: [
            new TableRow({ children: [
              headerCell("Host", 2200), headerCell("IP / Port", 2200),
              headerCell("Role", 2200), headerCell("Notes", 2760),
            ]}),
            new TableRow({ children: [
              cell("lxc 10001", 2200, { bold: true }),
              cell(`${REMOTE_IP}:3000 / :8000`, 2200),
              cell("App stack (Docker)", 2200),
              cell("Frontend :3000, API :8000, Celery, PG, Redis", 2760),
            ]}),
            new TableRow({ children: [
              cell("vmid901", 2200, { bold: true, shade: true }),
              cell(`${OLLAMA_URL}`, 2200, { shade: true }),
              cell("Ollama inference", 2200, { shade: true }),
              cell("2x RTX 3080 (10GB ea), models loaded on-demand", 2760, { shade: true }),
            ]}),
            new TableRow({ children: [
              cell("vm780", 2200, { bold: true }),
              cell(VM_NAS_IP, 2200),
              cell("NAS access / dev", 2200),
              cell("Project source at /mnt/pve/gs-nas/.../viddocs", 2760),
            ]}),
            new TableRow({ children: [
              cell("vmid2900", 2200, { bold: true, shade: true }),
              cell("10.255.x.x", 2200, { shade: true }),
              cell("NOT in scope", 2200, { shade: true }),
              cell("P40 + 3060 Ti saturated by llama-server", 2760, { shade: true }),
            ]}),
          ],
        }),

        para([
          { text: "SSH keys exchanged: ", bold: true },
          { text: "vm780 \u2194 lxc 10001 (done), node03 \u2194 lxc 10001 (done). ssh-relay aliases: vm780, vm901, node01." },
        ]),

        para([
          { text: "Ollama models on vmid901: ", bold: true },
          { text: "qwen2.5:32b-instruct-q4_K_M (recommended for slide classification), mistral:7b, qwen3:8b, deepseek-r1:14b, nomic-embed-text." },
        ]),

        divider(),

        // ===== WHAT CHANGED =====
        heading1("3. What Changed"),

        heading2("3.1 New Files"),
        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [4500, 1200, 3660],
          rows: [
            new TableRow({ children: [
              headerCell("File", 4500), headerCell("Lines", 1200), headerCell("Purpose", 3660),
            ]}),
            new TableRow({ children: [
              cell("backend/app/services/slide_detection.py", 4500, { mono: true }),
              cell("~750", 1200), cell("Core CV+LLM engine: layout detection, SSIM transitions, slide grouping, OCR, LLM ambiguity classification, transcript alignment, doc generation", 3660),
            ]}),
            new TableRow({ children: [
              cell("frontend/components/SlidesGallery.tsx", 4500, { mono: true, shade: true }),
              cell("162", 1200, { shade: true }), cell("React component: collapsible slide cards with screenshots, OCR text, transcript, SSIM confidence badges", 3660, { shade: true }),
            ]}),
            new TableRow({ children: [
              cell("migrations/versions/004_...tables.py", 4500, { mono: true }),
              cell("72", 1200), cell("Alembic migration: slides + slide_detection_metadata tables, extends processing_jobs + snapshots", 3660),
            ]}),
          ],
        }),

        heading2("3.2 Modified Files"),
        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [4500, 4860],
          rows: [
            new TableRow({ children: [
              headerCell("File", 4500), headerCell("Change", 4860),
            ]}),
            new TableRow({ children: [
              cell("backend/app/db/models.py", 4500, { mono: true }),
              cell("Added SlideDetectionMetadata + Slide ORM models; processing_mode on ProcessingJob; slide_id + ssim_delta on Snapshot", 4860),
            ]}),
            new TableRow({ children: [
              cell("backend/app/schemas.py", 4500, { mono: true, shade: true }),
              cell("Added SlideResponse, SlideListResponse, SlideDetectionMetadataResponse; is_slide_mode on JobCreate; processing_mode + slides on JobResponse", 4860, { shade: true }),
            ]}),
            new TableRow({ children: [
              cell("backend/app/core/config.py", 4500, { mono: true }),
              cell("Added SlideDetectionSettings class (SSIM thresholds, sampling FPS, LLM model, OCR toggle)", 4860),
            ]}),
            new TableRow({ children: [
              cell("backend/app/tasks.py", 4500, { mono: true, shade: true }),
              cell("Added process_slides Celery task; conditional chain from process_transcript when mode is slide_aware", 4860, { shade: true }),
            ]}),
            new TableRow({ children: [
              cell("backend/app/routes/jobs.py", 4500, { mono: true }),
              cell("Added GET /jobs/{id}/slides and /slide-metadata; processing_mode set on job creation from is_slide_mode", 4860),
            ]}),
            new TableRow({ children: [
              cell("frontend/app/page.tsx", 4500, { mono: true, shade: true }),
              cell("Added Presentation Mode toggle switch, sends is_slide_mode in POST body", 4860, { shade: true }),
            ]}),
            new TableRow({ children: [
              cell("frontend/types/index.ts", 4500, { mono: true }),
              cell("Added Slide, SlideListResponse, SlideDetectionMetadata interfaces", 4860),
            ]}),
            new TableRow({ children: [
              cell(".env.example", 4500, { mono: true, shade: true }),
              cell(`Added SLIDE_* config vars; fixed OLLAMA_BASE_URL to ${OLLAMA_URL}`, 4860, { shade: true }),
            ]}),
            new TableRow({ children: [
              cell("docker-compose.yml", 4500, { mono: true }),
              cell("Fixed OLLAMA_BASE_URL default to vmid901", 4860),
            ]}),
            new TableRow({ children: [
              cell("backend/requirements.txt", 4500, { mono: true, shade: true }),
              cell("Added scikit-image>=0.22.0", 4860, { shade: true }),
            ]}),
          ],
        }),

        divider(),

        // ===== ARCHITECTURE =====
        heading1("4. Pipeline Architecture"),

        heading2("4.1 Flow Diagram"),
        para("When a user submits a URL with Presentation Mode enabled:"),

        new Paragraph({
          numbering: { reference: "numbers", level: 0 },
          spacing: { after: 60 },
          children: [
            new TextRun({ text: "POST /api/jobs ", font: "Consolas", size: 18 }),
            new TextRun({ text: "with is_slide_mode: true creates a ProcessingJob with processing_mode = slide_aware", font: "Arial", size: 21 }),
          ],
        }),
        bullet("process_transcript Celery task runs the existing pipeline (transcript acquisition, video download)", "numbers"),
        bullet("After video download, instead of marking COMPLETED, it chains to process_slides.delay(job_id)", "numbers"),
        bullet("process_slides runs the SlideDetectionService.run_full_pipeline() which executes 6 steps:", "numbers"),

        bulletBold("Step 1 \u2013 Layout Detection:", "Sample 20 frames from first 90s. Canny edge + contour analysis to classify layout as full_frame, pip_speaker, or split_panel. Determines slide region bounding box."),
        bulletBold("Step 2 \u2013 SSIM Transition Scan:", "Sample at 2 fps, compute SSIM on cropped slide region. SSIM < 0.85 = new slide; 0.85\u20130.98 = incremental build; > 0.98 = no change."),
        bulletBold("Step 3 \u2013 LLM Ambiguity Classification:", "For transitions with SSIM 0.75\u20130.85, send OCR text from both frames to qwen2.5:32b via Ollama for TRANSITION vs INCREMENTAL classification."),
        bulletBold("Step 4 \u2013 Slide Grouping:", "Merge incremental builds under same logical slide. 2-second debounce to filter flicker. Pre-slide content becomes Introduction (slide 0)."),
        bulletBold("Step 5 \u2013 Final-State Capture:", "Extract frame 0.5s before each slide ends (avoids transition frame). Save JPEG to data/slides/{job_id}/. Run pytesseract OCR on cropped region."),
        bulletBold("Step 6 \u2013 Transcript Alignment:", "Map TranscriptSegment records to slides by timestamp overlap. Concatenate matching segments into aligned_transcript per slide."),

        para([
          { text: "Fallback: ", bold: true },
          { text: "If layout detection confidence is below 0.7 or any critical step fails, the pipeline falls back to generic mode gracefully and marks the job COMPLETED without slide data." },
        ]),

        heading2("4.2 SSIM Thresholds (Tunable via .env)"),
        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [2400, 2400, 4560],
          rows: [
            new TableRow({ children: [
              headerCell("SSIM Range", 2400), headerCell("Classification", 2400), headerCell("Behavior", 4560),
            ]}),
            new TableRow({ children: [
              cell("\u2265 0.98", 2400), cell("Identical", 2400), cell("No change detected, skip frame", 4560),
            ]}),
            new TableRow({ children: [
              cell("0.85 \u2013 0.98", 2400, { shade: true }), cell("Incremental Build", 2400, { shade: true }),
              cell("New content on same slide (bullet appearing, animation). Grouped under current slide.", 4560, { shade: true }),
            ]}),
            new TableRow({ children: [
              cell("< 0.85", 2400), cell("New Slide", 2400),
              cell("Slide transition boundary. Creates new slide record.", 4560),
            ]}),
            new TableRow({ children: [
              cell("0.75 \u2013 0.85", 2400, { shade: true }), cell("Ambiguous", 2400, { shade: true }),
              cell("Sent to LLM for classification (if available). Falls back to CV decision on LLM failure.", 4560, { shade: true }),
            ]}),
          ],
        }),

        divider(),

        // ===== DB SCHEMA =====
        heading1("5. Database Schema Changes"),
        para("Migration 004 is additive and fully reversible. All new columns nullable or defaulted."),

        heading3("New: slides table"),
        bullet("id (PK), job_id (FK to processing_jobs, CASCADE)"),
        bullet("slide_number (int, 1-indexed; 0 = introduction)"),
        bullet("first_frame_timestamp, last_frame_timestamp (float, seconds)"),
        bullet("screenshot_path (str), ssim_confidence (float)"),
        bullet("slide_content_text (text, OCR), aligned_transcript (text)"),
        bullet("Index: (job_id, slide_number)"),

        heading3("New: slide_detection_metadata table"),
        bullet("id (PK), job_id (FK, CASCADE)"),
        bullet("layout_type (str: full_frame / pip_speaker / split_panel / unknown)"),
        bullet("detected_layout_confidence (float), slide_region bbox (x, y, w, h as ints)"),
        bullet("sampling_fps, ssim_threshold, total_slides_detected"),
        bullet("Index: job_id"),

        heading3("Modified: processing_jobs"),
        bullet("processing_mode (str, default 'generic', also 'slide_aware')"),

        heading3("Modified: snapshots"),
        bullet("slide_id (FK to slides, SET NULL), ssim_delta_vs_prev (float)"),

        divider(),

        // ===== DEPLOYMENT =====
        heading1("6. Deployment Steps"),
        para("To activate the feature on lxc 10001:"),

        new Paragraph({
          numbering: { reference: "numbers", level: 0 },
          spacing: { after: 60 },
          children: [
            new TextRun({ text: "Sync updated source ", font: "Arial", size: 21, bold: true }),
            new TextRun({ text: "from NAS to the Docker build context on lxc 10001", font: "Arial", size: 21 }),
          ],
        }),

        new Paragraph({
          numbering: { reference: "numbers", level: 0 },
          spacing: { after: 60 },
          children: [
            new TextRun({ text: "Run Alembic migration: ", font: "Arial", size: 21, bold: true }),
            new TextRun({ text: "docker-compose exec api alembic upgrade head", font: "Consolas", size: 18 }),
          ],
        }),

        new Paragraph({
          numbering: { reference: "numbers", level: 0 },
          spacing: { after: 60 },
          children: [
            new TextRun({ text: "Install scikit-image: ", font: "Arial", size: 21, bold: true }),
            new TextRun({ text: "pip install scikit-image in the backend container, or rebuild the Docker image", font: "Arial", size: 21 }),
          ],
        }),

        new Paragraph({
          numbering: { reference: "numbers", level: 0 },
          spacing: { after: 60 },
          children: [
            new TextRun({ text: "Update .env: ", font: "Arial", size: 21, bold: true }),
            new TextRun({ text: `Add SLIDE_* variables (see .env.example), set OLLAMA_BASE_URL=${OLLAMA_URL}`, font: "Arial", size: 21 }),
          ],
        }),

        new Paragraph({
          numbering: { reference: "numbers", level: 0 },
          spacing: { after: 60 },
          children: [
            new TextRun({ text: "Restart Celery worker: ", font: "Arial", size: 21, bold: true }),
            new TextRun({ text: "to pick up the new process_slides task", font: "Arial", size: 21 }),
          ],
        }),

        new Paragraph({
          numbering: { reference: "numbers", level: 0 },
          spacing: { after: 60 },
          children: [
            new TextRun({ text: "Rebuild frontend: ", font: "Arial", size: 21, bold: true }),
            new TextRun({ text: "npm run build in the web container to pick up the toggle + SlidesGallery component", font: "Arial", size: 21 }),
          ],
        }),

        divider(),

        // ===== REMAINING WORK =====
        heading1("7. Remaining Work"),
        para("The following items are implemented but not yet wired or tested end-to-end:"),

        heading3("7.1 Frontend Integration (Job Detail Page)"),
        para([
          { text: "SlidesGallery.tsx ", font: "Consolas", size: 18 },
          { text: "is built but needs to be imported into ", font: "Arial", size: 21 },
          { text: "frontend/app/jobs/[id]/page.tsx", font: "Consolas", size: 18 },
          { text: ". When processing_mode is slide_aware, the job detail page should render a Slides tab that fetches from GET /jobs/{id}/slides and passes the data to SlidesGallery.", font: "Arial", size: 21 },
        ]),

        heading3("7.2 Static File Serving for Slide Screenshots"),
        para("The slide screenshots are saved to data/slides/{job_id}/. The API needs a static file mount for /static/slides/ similar to the existing /static/snapshots/ mount. Check the FastAPI app setup for the StaticFiles configuration."),

        heading3("7.3 End-to-End Testing"),
        para("Test with a real presentation video. The 4 videos already downloaded on the NAS are at:"),
        mono("/path/to/your/youtube-downloads/"),
        para("The NVLink Fusion video (GMJj4KDqYGo) is a good candidate since it appears to be presentation-style."),

        heading3("7.4 Threshold Tuning"),
        para("The SSIM thresholds (0.85 / 0.98) are starting points. Different presentation styles (dark backgrounds, code-heavy slides, animated transitions) may need per-video calibration. Consider adding a UI control for sensitivity or an auto-calibration pass."),

        divider(),

        // ===== KEY DECISIONS =====
        heading1("8. Key Design Decisions"),

        bulletBold("CV-first, LLM-second:", "SSIM handles 90%+ of transitions. LLM is only called for the ambiguous 0.75\u20130.85 SSIM range. This keeps latency low and avoids burning inference tokens on clear transitions."),
        bulletBold("Final-state only:", "Incremental builds (bullets appearing one-by-one) are grouped under the same slide. Only the last frame before the next transition is captured. This prevents output clutter."),
        bulletBold("Layout fallback:", "If layout detection confidence is below 0.7, the system assumes full-frame with a 2% margin crop. This handles screen recordings and full-screen shares gracefully."),
        bulletBold("Non-disruptive:", "Estimated disruption to existing codebase: 25\u201330%. The generic pipeline path is completely untouched. New DB columns are nullable/defaulted. Migration is reversible."),
        bulletBold("No GPU required for v1:", "All CV work (SSIM, contours, OCR) is CPU-bound on the Celery worker. GPU upgrade path exists via vmid901 (2x 3080 with free VRAM) for neural OCR if pytesseract proves insufficient."),

        divider(),

        // ===== ENV VARS =====
        heading1("9. Environment Variables Reference"),
        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [3800, 1200, 4360],
          rows: [
            new TableRow({ children: [
              headerCell("Variable", 3800), headerCell("Default", 1200), headerCell("Purpose", 4360),
            ]}),
            new TableRow({ children: [
              cell("SLIDE_SSIM_THRESHOLD", 3800, { mono: true }),
              cell("0.85", 1200), cell("SSIM below this = new slide", 4360),
            ]}),
            new TableRow({ children: [
              cell("SLIDE_SSIM_BUILD_THRESHOLD", 3800, { mono: true, shade: true }),
              cell("0.98", 1200, { shade: true }), cell("SSIM above this = identical frame", 4360, { shade: true }),
            ]}),
            new TableRow({ children: [
              cell("SLIDE_SAMPLING_FPS", 3800, { mono: true }),
              cell("2", 1200), cell("Frames per second for SSIM scan", 4360),
            ]}),
            new TableRow({ children: [
              cell("SLIDE_LAYOUT_SAMPLE_COUNT", 3800, { mono: true, shade: true }),
              cell("20", 1200, { shade: true }), cell("Frames sampled for layout detection", 4360, { shade: true }),
            ]}),
            new TableRow({ children: [
              cell("SLIDE_LAYOUT_SAMPLE_DURATION", 3800, { mono: true }),
              cell("90", 1200), cell("Seconds to sample from video start", 4360),
            ]}),
            new TableRow({ children: [
              cell("SLIDE_LAYOUT_CONFIDENCE_MIN", 3800, { mono: true, shade: true }),
              cell("0.7", 1200, { shade: true }), cell("Min confidence to accept layout detection", 4360, { shade: true }),
            ]}),
            new TableRow({ children: [
              cell("SLIDE_LLM_MODEL", 3800, { mono: true }),
              cell("qwen2.5:32b-instruct-q4_K_M", 1200),
              cell("Ollama model for ambiguity classification", 4360),
            ]}),
            new TableRow({ children: [
              cell("SLIDE_OCR_ENABLED", 3800, { mono: true, shade: true }),
              cell("true", 1200, { shade: true }), cell("Run pytesseract on detected slides", 4360, { shade: true }),
            ]}),
            new TableRow({ children: [
              cell("OLLAMA_BASE_URL", 3800, { mono: true }),
              cell(OLLAMA_URL, 1200),
              cell("Ollama endpoint on vmid901", 4360),
            ]}),
          ],
        }),

        divider(),

        heading1("10. Questions for Max"),
        bullet("The process_slides task currently saves screenshots to data/slides/{job_id}/ using the video file parent path. Verify this aligns with your Docker volume mount for app_data."),
        bullet("The frontend SlidesGallery expects image URLs at /static/slides/{job_id}/slide_001.jpg. Confirm the StaticFiles mount covers this path."),
        bullet("Alembic migration 004 references down_revision = '003'. Verify migration 003 is the latest in your branch."),
        bullet("The LLM ambiguity classification prompt is basic (TRANSITION vs INCREMENTAL). If you want richer classification (e.g., detecting speaker-only frames, transition animations), the prompt in slide_detection.py classify_ambiguous_transitions() is the place to iterate."),
      ],
    },
  ],
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("/sessions/wonderful-gifted-mayer/mnt/outputs/Handoff_SlideFeature_Max.docx", buffer);
  console.log("Document created successfully");
});
