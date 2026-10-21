const audioInput = document.querySelector("#audio-file");
const audioPlayer = document.querySelector("#audio-player");
const canvas = document.querySelector("#waveform");
const context = canvas.getContext("2d");
const lineList = document.querySelector("#line-list");
const exportButton = document.querySelector("#export-button");
const autoSyncButton = document.querySelector("#auto-sync-button");
const sourceFolderInput = document.querySelector("#source-folder-name");
const uploadRow = document.querySelector(".upload-row");
const editorActions = document.querySelector(".editor-actions");
const generateFieldsButton = document.querySelector("#generate-fields-button");
const vocabularyInput = document.querySelector("#vocabulary-input");
const vocabularyInputLabel = document.querySelector("#vocabulary-input-label");
const vocabularyPreview = document.querySelector("#vocabulary-preview");
const vocabularyToggle = document.querySelector("#vocabulary-toggle");
const statusBox = document.querySelector("#status");

let audioFile = null;
let audioUrl = null;
let audioBuffer = null;
let lines = [];
let dialogueHeading = null;
let selectedLine = 0;
let previewingLine = null;
let lineWaveformDrag = null;
let suppressLineWaveformClick = null;
let preparedDialogueText = null;
let vocabularyRubyByWord = new Map();
let generatedVocabularySignature = null;

function showStatus(message, kind = "info") {
  statusBox.textContent = message;
  statusBox.className = `status ${kind}`;
}

function playAudioFromTime(time) {
  if (!audioFile || !Number.isFinite(audioPlayer.duration)) return;
  previewingLine = null;
  audioPlayer.currentTime = Math.max(0, Math.min(time, audioPlayer.duration));
  updatePreviewControls();
  audioPlayer.play().catch((error) => showStatus(`Could not play audio: ${error.message}`, "error"));
}

function clearStatus() {
  statusBox.className = "status hidden";
  statusBox.textContent = "";
}

function splitDialogueRow(text) {
  const separators = /[。！？!?，,]/gu;
  const pieces = [];
  let start = 0;

  for (const match of text.matchAll(separators)) {
    const separator = match[0];
    const end = match.index + 1;
    const piece = text.slice(start, end).trim();
    if (/[，,]/u.test(separator) && /^(?:不过|但是|然后|接着|之后|另外|此外|这样|所以|因此|而且|同时)[，,]$/u.test(piece)) {
      continue;
    }
    if (piece) {
      pieces.push(piece);
    }
    start = end;
  }

  const remainder = text.slice(start).trim();
  if (remainder) pieces.push(remainder);
  return pieces;
}

function parseDialogue(text) {
  const rows = text.split(/\r?\n/).map((row) => row.trim()).filter(Boolean);
  dialogueHeading = null;
  const isSpeakerLine = (row) => /^[^：:\r\n]{1,16}[：:]/u.test(row);
  const firstRow = rows[0] ?? "";
  const looksLikeHeading = firstRow
    && !/[。！？!?]$/.test(firstRow)
    && rows.slice(1).some(isSpeakerLine);
  if (looksLikeHeading) {
    dialogueHeading = firstRow;
  }

  const dialogueRows = [];
  let previousRowHadSpeaker = false;
  rows.forEach((row, index) => {
    if (looksLikeHeading && index === 0) return;
    const hasSpeaker = isSpeakerLine(row);
    const trimmed = row.replace(/^[^：:\r\n]{1,16}[：:]\s*/u, "").trim();
    if (!trimmed) return;

    const previous = dialogueRows.at(-1);
    const isSpeakerContinuation = !hasSpeaker
      && previousRowHadSpeaker
      && previous
      && !/[。！？!?]$/u.test(previous);
    if (isSpeakerContinuation) {
      dialogueRows[dialogueRows.length - 1] += trimmed;
    } else {
      dialogueRows.push(trimmed);
    }
    previousRowHadSpeaker = hasSpeaker || isSpeakerContinuation;
  });

  return dialogueRows.flatMap(splitDialogueRow);
}

function parseVocabulary() {
  const entries = [];
  const invalidLines = [];
  vocabularyInput.value.split(/\r?\n/u).forEach((row, index) => {
    const trimmed = row.trim();
    if (!trimmed) return;
    const separator = trimmed.search(/\s/u);
    if (separator <= 0 || !trimmed.slice(separator).trim()) {
      invalidLines.push(index + 1);
      return;
    }
    const word = trimmed.slice(0, separator);
    const remainder = trimmed.slice(separator).trim();
    const tokens = remainder.split(/\s+/u);
    let pronunciation = "";
    if (/^[a-züv]+[1-5]$/iu.test(tokens[0])) {
      while (tokens.length && /^[a-züv]+[1-5]$/iu.test(tokens[0])) {
        pronunciation += tokens.shift();
      }
    } else {
      const joinedPinyin = tokens[0];
      if (/^(?:[a-züv]+[1-5])+$/iu.test(joinedPinyin)) {
        pronunciation = joinedPinyin;
        tokens.shift();
      }
    }
    const definition = tokens.join(" ").trim();
    if (!definition) {
      invalidLines.push(index + 1);
      return;
    }
    entries.push({
      word,
      pronunciation,
      definition,
    });
  });
  return { entries, invalidLines };
}

function vocabularySignature(entries) {
  return JSON.stringify(entries.map(({ word, pronunciation }) => [word, pronunciation]));
}

function escapeHtml(text) {
  return text.replace(/[&<>"']/gu, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function vocabularyFieldsForLine(sentence, entries) {
  const matched = entries.filter(({ word }) => sentence.includes(word));
  return {
    Word: matched.map(({ word }) => word).join(","),
    WordDef: matched.map(({ definition }) => escapeHtml(definition)).join("<hr>"),
    WordRuby: matched.map(({ word }) => vocabularyRubyByWord.get(word) || "").join(","),
  };
}

function updateVocabularyIndicator(card, sentence) {
  const indicator = card.querySelector(".vocabulary-match");
  if (!indicator) return;
  const { entries } = parseVocabulary();
  const matches = entries
    .filter(({ word }) => sentence.includes(word))
    .map(({ word }) => word);
  indicator.hidden = matches.length === 0;
  indicator.textContent = matches.length
    ? `New vocab: ${matches.join(", ")}`
    : "";
  indicator.title = matches.join(", ");
  indicator.setAttribute(
    "aria-label",
    matches.length ? `New vocabulary in this line: ${matches.join(", ")}` : "",
  );
}

function renderVocabularyPreview(entries) {
  vocabularyPreview.replaceChildren();
  entries.forEach(({ word, definition }) => {
    const item = document.createElement("div");
    item.className = "vocabulary-entry";
    const ruby = document.createElement("div");
    ruby.className = "vocabulary-ruby";
    ruby.innerHTML = sanitizeStudyHtml(vocabularyRubyByWord.get(word) || escapeHtml(word));
    const meaning = document.createElement("div");
    meaning.className = "vocabulary-definition";
    meaning.textContent = definition;
    item.append(ruby, meaning);
    vocabularyPreview.append(item);
  });
}

function toneMarkedPinyinToNumbers(rubyHtml) {
  const parsed = new DOMParser().parseFromString(rubyHtml, "text/html");
  const toneMarks = new Map([
    ["ā", "a"], ["á", "a"], ["ǎ", "a"], ["à", "a"],
    ["ē", "e"], ["é", "e"], ["ě", "e"], ["è", "e"],
    ["ī", "i"], ["í", "i"], ["ǐ", "i"], ["ì", "i"],
    ["ō", "o"], ["ó", "o"], ["ǒ", "o"], ["ò", "o"],
    ["ū", "u"], ["ú", "u"], ["ǔ", "u"], ["ù", "u"],
    ["ǖ", "ü"], ["ǘ", "ü"], ["ǚ", "ü"], ["ǜ", "ü"],
  ]);
  return [...parsed.querySelectorAll("ruby")].map((ruby) => {
    const reading = ruby.querySelector("rt")?.textContent || "";
    const toneClass = [...(ruby.closest("span")?.classList || [])]
      .find((name) => /^tone[1-5]$/u.test(name));
    const tone = toneClass?.slice(-1) || "5";
    const plain = [...reading.toLowerCase()]
      .map((character) => toneMarks.get(character) || character)
      .join("");
    return `${plain}${tone}`;
  }).join("");
}

function setVocabularyPreviewMode(enabled) {
  if (!enabled && !vocabularyPreview.hidden) {
    const { entries } = parseVocabulary();
    vocabularyInput.value = entries.map(({ word, definition }) => {
      const pronunciation = toneMarkedPinyinToNumbers(vocabularyRubyByWord.get(word) || "");
      return [word, pronunciation, definition].filter(Boolean).join(" ");
    }).join("\n");
    generatedVocabularySignature = vocabularySignature(parseVocabulary().entries);
  }
  vocabularyInput.hidden = enabled;
  vocabularyInputLabel.hidden = enabled;
  vocabularyPreview.hidden = !enabled;
  vocabularyToggle.textContent = enabled ? "Edit vocabulary" : "Show formatted vocabulary";
}

function formatTime(seconds) {
  if (seconds === null || !Number.isFinite(seconds)) return "—";
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${(seconds % 60).toFixed(2).padStart(5, "0")}`;
}

function validLine(line) {
  return line.start !== null && line.end !== null && line.end > line.start;
}

function allLinesTimed() {
  return lines.length > 0 && lines.every(validLine);
}

function updateExportState() {
  const canExport = Boolean(audioFile && audioPlayer.duration && allLinesTimed());
  exportButton.disabled = !canExport;
  document.querySelector("#export-hint").textContent = !audioFile
    ? "Choose an MP3 to continue."
    : allLinesTimed()
      ? "All lines are timed. Your clips are ready to export."
      : "Drag across a waveform to set a start and end time for every line.";
}

function sanitizeStudyHtml(html) {
  const parsed = new DOMParser().parseFromString(html, "text/html");
  const safeRoot = document.createElement("div");
  const discardedTags = new Set([
    "base",
    "embed",
    "iframe",
    "link",
    "math",
    "meta",
    "object",
    "script",
    "style",
    "svg",
    "template",
  ]);

  function copySafeNode(node, parent) {
    if (node.nodeType === Node.TEXT_NODE) {
      parent.append(document.createTextNode(node.textContent || ""));
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;

    const tag = node.tagName.toLowerCase();
    if (discardedTags.has(tag)) return;
    if (tag === "br" || tag === "hr") {
      parent.append(document.createElement(tag));
      return;
    }
    if (tag === "span") {
      const toneClass = [...node.classList].find((name) => /^tone[1-5]$/u.test(name));
      if (toneClass) {
        const span = document.createElement("span");
        span.className = toneClass;
        node.childNodes.forEach((child) => copySafeNode(child, span));
        parent.append(span);
        return;
      }
    } else if (tag === "ruby" || tag === "rt") {
      const element = document.createElement(tag);
      node.childNodes.forEach((child) => copySafeNode(child, element));
      parent.append(element);
      return;
    }

    node.childNodes.forEach((child) => copySafeNode(child, parent));
  }

  parsed.body.childNodes.forEach((node) => copySafeNode(node, safeRoot));
  return safeRoot.innerHTML;
}

function renderLines() {
  lineList.replaceChildren();
  document.querySelector("#line-count").textContent = `${lines.length} ${lines.length === 1 ? "line" : "lines"}`;

  lines.forEach((line, index) => {
    const card = document.createElement("article");
    card.className = `line-card${index === selectedLine ? " selected" : ""}`;
    card.dataset.index = String(index);

    const marker = document.createElement("div");
    marker.className = "line-marker";

    const number = document.createElement("div");
    number.className = "line-number";
    number.textContent = String(index + 1).padStart(2, "0");

    const content = document.createElement("div");
    content.className = "line-content";

    const sentence = document.createElement("textarea");
    sentence.className = "sentence";
    sentence.rows = 1;
    sentence.setAttribute("aria-label", `Dialogue line ${index + 1}`);
    sentence.value = line.sentence;
    sentence.addEventListener("input", () => {
      line.sentence = sentence.value;
      updateVocabularyIndicator(card, line.sentence);
      updateExportState();
    });
    sentence.addEventListener("focus", () => selectLine(index));

    const controls = document.createElement("div");
    controls.className = "line-controls";
    const vocabularyIndicator = document.createElement("span");
    vocabularyIndicator.className = "vocabulary-match";
    controls.append(vocabularyIndicator);
    const readout = document.createElement("span");
    readout.className = "time-readout";
    readout.textContent = `${formatTime(line.start)}  →  ${formatTime(line.end)}`;
    controls.append(readout);

    if (line.matched === true && !line.manualTiming) {
      const matchScore = document.createElement("span");
      matchScore.className = "match-score";
      matchScore.textContent = `Text match ${Math.round(line.confidence * 100)}%`;
      controls.append(matchScore);
    } else if (line.matched === false) {
      const unmatched = document.createElement("span");
      unmatched.className = "match-score unmatched";
      unmatched.textContent = "Not matched — drag to set timing";
      controls.append(unmatched);
    } else if (line.manualTiming) {
      const manual = document.createElement("span");
      manual.className = "match-score";
      manual.textContent = "Manual timing";
      controls.append(manual);
    }

    const gloss = document.createElement("textarea");
    gloss.className = "gloss-input";
    gloss.rows = 1;
    gloss.placeholder = "English translation (editable)";
    gloss.setAttribute("aria-label", `English translation for line ${index + 1}`);
    gloss.value = line.gloss;
    gloss.addEventListener("input", () => { line.gloss = gloss.value; });

    const studyFields = document.createElement("details");
    studyFields.className = "study-fields";
    studyFields.open = Boolean(line.studyFieldsOpen);
    const studyFieldsSummary = document.createElement("summary");
    studyFieldsSummary.textContent = "Fields";
    studyFields.append(studyFieldsSummary);
    const translationField = document.createElement("div");
    translationField.className = "study-field";
    const translationLabel = document.createElement("div");
    translationLabel.className = "study-field-heading";
    const translationLabelText = document.createElement("span");
    translationLabelText.className = "study-field-label";
    translationLabelText.textContent = "English translation";
    translationLabel.append(translationLabelText);
    translationField.append(translationLabel, gloss);
    studyFields.append(translationField);
    for (const [field, label] of [
      ["reading", "Reading"],
      ["ruby", "Ruby"],
      ["dictionaryGloss", "Dictionary gloss"],
    ]) {
      const fieldLabel = document.createElement("div");
      fieldLabel.className = "study-field";
      const fieldHeading = document.createElement("div");
      fieldHeading.className = "study-field-heading";
      const labelText = document.createElement("span");
      labelText.className = "study-field-label";
      labelText.textContent = label;

      const editorToolbar = document.createElement("div");
      editorToolbar.className = "study-field-toolbar";
      const modeButton = document.createElement("button");
      modeButton.type = "button";
      modeButton.className = "study-field-mode";
      const sourceMode = `${field}SourceMode`;
      modeButton.textContent = line[sourceMode] ? "Preview" : "Edit HTML";

      const formattedEditor = document.createElement("div");
      formattedEditor.className = "study-field-preview";
      formattedEditor.contentEditable = "true";
      formattedEditor.setAttribute("role", "textbox");
      formattedEditor.setAttribute("aria-multiline", "true");
      formattedEditor.setAttribute("aria-label", `${label} for line ${index + 1}`);
      formattedEditor.spellcheck = false;
      formattedEditor.innerHTML = sanitizeStudyHtml(line[field] || "");
      formattedEditor.hidden = Boolean(line[sourceMode]);
      formattedEditor.addEventListener("input", () => {
        line[field] = formattedEditor.innerHTML;
      });
      formattedEditor.addEventListener("blur", () => {
        const safeHtml = sanitizeStudyHtml(formattedEditor.innerHTML);
        formattedEditor.innerHTML = safeHtml;
        line[field] = safeHtml;
      });

      const sourceEditor = document.createElement("textarea");
      sourceEditor.className = "study-field-source";
      sourceEditor.rows = 3;
      sourceEditor.value = line[field] || "";
      sourceEditor.setAttribute("aria-label", `${label} HTML for line ${index + 1}`);
      sourceEditor.hidden = !line[sourceMode];
      sourceEditor.addEventListener("input", () => { line[field] = sourceEditor.value; });

      modeButton.addEventListener("click", () => {
        line[sourceMode] = !line[sourceMode];
        if (line[sourceMode]) {
          sourceEditor.value = line[field] || "";
          sourceEditor.hidden = false;
          formattedEditor.hidden = true;
          modeButton.textContent = "Preview";
          sourceEditor.focus();
        } else {
          line[field] = sanitizeStudyHtml(sourceEditor.value);
          formattedEditor.innerHTML = line[field];
          sourceEditor.hidden = true;
          formattedEditor.hidden = false;
          modeButton.textContent = "Edit HTML";
          formattedEditor.focus();
        }
      });

      editorToolbar.append(modeButton);
      fieldHeading.append(labelText, editorToolbar);
      fieldLabel.append(fieldHeading, formattedEditor, sourceEditor);
      studyFields.append(fieldLabel);
    }
    studyFields.addEventListener("toggle", () => {
      line.studyFieldsOpen = studyFields.open;
    });

    const previewRow = document.createElement("div");
    previewRow.className = "line-preview-row";
    const lineWaveform = document.createElement("canvas");
    lineWaveform.className = "line-waveform";
    lineWaveform.tabIndex = audioBuffer ? 0 : -1;
    lineWaveform.setAttribute("role", "button");
    lineWaveform.setAttribute(
      "aria-label",
      `Line ${index + 1} waveform. Drag to set clip start and end. Click to listen.`,
    );
    lineWaveform.setAttribute("aria-disabled", String(!audioBuffer));
    lineWaveform.addEventListener("pointerdown", (event) => {
      if (!audioBuffer || event.button !== 0) return;
      event.preventDefault();
      lineWaveform.setPointerCapture(event.pointerId);
      lineWaveformDrag = {
        index,
        pointerId: event.pointerId,
        startX: event.clientX,
        startTime: lineWaveformTimeAt(lineWaveform, index, event.clientX),
        currentTime: lineWaveformTimeAt(lineWaveform, index, event.clientX),
        moved: false,
      };
    });
    lineWaveform.addEventListener("pointermove", (event) => {
      if (!lineWaveformDrag || lineWaveformDrag.pointerId !== event.pointerId) return;
      lineWaveformDrag.currentTime = lineWaveformTimeAt(lineWaveform, index, event.clientX);
      lineWaveformDrag.moved ||= Math.abs(event.clientX - lineWaveformDrag.startX) >= 4;
      drawLineWaveforms();
    });
    const finishWaveformDrag = (event) => {
      if (!lineWaveformDrag || lineWaveformDrag.pointerId !== event.pointerId) return;
      const drag = lineWaveformDrag;
      lineWaveformDrag = null;
      if (drag.moved && Math.abs(drag.currentTime - drag.startTime) >= 0.15) {
        suppressLineWaveformClick = index;
        setLineTimingFromDrag(index, drag.startTime, drag.currentTime);
        setTimeout(() => { suppressLineWaveformClick = null; }, 0);
      }
    };
    lineWaveform.addEventListener("pointerup", finishWaveformDrag);
    lineWaveform.addEventListener("pointercancel", finishWaveformDrag);
    lineWaveform.addEventListener("click", (event) => {
      if (suppressLineWaveformClick === index) {
        suppressLineWaveformClick = null;
        return;
      }
      const time = lineWaveformTimeAt(lineWaveform, index, event.clientX);
      if (validLine(line) && time >= line.start && time <= line.end) {
        playLinePreview(index, time);
      } else {
        playAudioFromTime(time);
      }
    });
    lineWaveform.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        if (validLine(line)) {
          playLinePreview(index);
        } else {
          const range = lineWaveformRange(index);
          playAudioFromTime((range.start + range.end) / 2);
        }
      }
    });

    const previewButton = document.createElement("button");
    previewButton.type = "button";
    previewButton.className = "line-preview-button";
    previewButton.dataset.line = String(index);
    previewButton.addEventListener("click", () => {
      if (previewingLine === index && !audioPlayer.paused) {
        stopLinePreview();
      } else {
        playLinePreview(index);
      }
    });
    marker.append(number, previewButton);
    previewRow.append(lineWaveform);

    content.append(sentence, previewRow, controls, studyFields);
    card.append(marker, content);
    lineList.append(card);
    updateVocabularyIndicator(card, line.sentence);
  });

  updateExportState();
  updatePreviewControls();
  drawWaveform();
}

vocabularyInput.addEventListener("input", () => {
  lineList.querySelectorAll(".line-card").forEach((card, index) => {
    updateVocabularyIndicator(card, lines[index]?.sentence || "");
  });
});

function selectLine(index) {
  selectedLine = index;
  document.querySelectorAll(".line-card").forEach((card, cardIndex) => {
    card.classList.toggle("selected", cardIndex === selectedLine);
  });
  drawWaveform();
}

function median(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

function lineWaveformRange(index) {
  const duration = audioPlayer.duration;
  const line = lines[index];
  if (!Number.isFinite(duration) || duration <= 0) return { start: 0, end: 0 };

  if (validLine(line)) {
    const padding = Math.max(2, (line.end - line.start) * 0.15);
    return {
      start: Math.max(0, line.start - padding),
      end: Math.min(duration, line.end + padding),
    };
  }

  const timedDurations = lines.filter(validLine).map((item) => item.end - item.start);
  const estimatedDuration = median(timedDurations) || 5;
  const previous = lines.slice(0, index).reverse().find(validLine);
  const next = lines.slice(index + 1).find(validLine);
  let center;
  if (previous && next) {
    center = (previous.end + next.start) / 2;
  } else if (previous) {
    center = previous.end + estimatedDuration / 2;
  } else if (next) {
    center = next.start - estimatedDuration / 2;
  } else {
    center = duration * ((index + 0.5) / lines.length);
  }
  const rangeWidth = Math.max(8, estimatedDuration * 2 + 4);
  const start = Math.max(0, Math.min(duration - rangeWidth, center - rangeWidth / 2));
  return { start, end: Math.min(duration, start + rangeWidth) };
}

function lineWaveformTimeAt(lineCanvas, index, clientX) {
  const bounds = lineCanvas.getBoundingClientRect();
  const range = lineWaveformRange(index);
  const ratio = Math.max(0, Math.min(1, (clientX - bounds.left) / bounds.width));
  return range.start + ratio * (range.end - range.start);
}

function setLineTimingFromDrag(index, start, end) {
  const line = lines[index];
  line.start = Math.max(0, Math.min(start, end));
  line.end = Math.min(audioPlayer.duration, Math.max(start, end));
  line.confidence = null;
  line.matched = null;
  line.manualTiming = true;
  if (previewingLine === index) stopLinePreview();
  selectedLine = index;
  renderLines();
  showStatus(
    `Line ${index + 1} timing set to ${formatTime(line.start)}–${formatTime(line.end)}.`,
    "success",
  );
}

const MIN_CLAUSE_PAUSE_SECONDS = 0.4;

function hasValidMatch(match) {
  return Boolean(
    match
    && Number.isFinite(match.start)
    && Number.isFinite(match.end)
    && match.end > match.start
  );
}

function mergeLinesAtAudioPauses(candidateLines, candidateMatches) {
  const groups = [];
  candidateLines.forEach((sentence, sourceIndex) => {
    const match = candidateMatches[sourceIndex] ?? null;
    const previous = groups.at(-1);
    const hasCommaBoundary = previous && /[，,]$/u.test(previous.sentence);
    const startsClearClause = /^(?:不过|但是|可是|很多|你是怎么|然后|接着|之后|有空儿|有空|慢慢地|另外|此外|所以|因此|而且|同时|这样|结果|后面|最后|其实|实在|就|看来|不但|否则|我没做完|有几个)/u.test(sentence.trimStart());
    const continuesPairedClause = /(?:不但|不只|不仅)[^，,。！？!?]*[，,]$/u.test(previous?.sentence ?? "")
      && /^(?:还|也)/u.test(sentence.trimStart());
    const hasShortPause = Number.isFinite(previous?.match?.pause_after)
      && previous.match.pause_after < MIN_CLAUSE_PAUSE_SECONDS;
    const shouldMerge = hasCommaBoundary
      && !startsClearClause
      && (
        continuesPairedClause
        || (
          hasValidMatch(previous.match)
          && hasValidMatch(match)
          && hasShortPause
        )
      );

    if (shouldMerge) {
      previous.sentence += sentence;
      previous.sourceIndices.push(sourceIndex);
      previous.match.end = match.end;
      previous.match.confidence = Math.min(previous.match.confidence, match.confidence);
      previous.match.matched_text += match.matched_text;
      previous.match.pause_after = match.pause_after;
      return;
    }

    if (hasCommaBoundary) {
      previous.sentence = `${previous.sentence.slice(0, -1)}。`;
    }
    groups.push({ sentence, match, sourceIndices: [sourceIndex] });
  });

  const last = groups.at(-1);
  if (last && /[，,]$/u.test(last.sentence)) {
    last.sentence = `${last.sentence.slice(0, -1)}。`;
  }
  return groups;
}

function drawWaveform() {
  const bounds = canvas.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return;
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.round(bounds.width * scale);
  canvas.height = Math.round(bounds.height * scale);
  context.setTransform(scale, 0, 0, scale, 0, 0);
  context.clearRect(0, 0, bounds.width, bounds.height);

  if (audioBuffer) {
    const samples = audioBuffer.getChannelData(0);
    const step = Math.max(1, Math.floor(samples.length / bounds.width));
    const center = bounds.height / 2;
    context.fillStyle = "#6f7ea6";
    for (let x = 0; x < bounds.width; x += 1) {
      let minimum = 1;
      let maximum = -1;
      const start = x * step;
      const end = Math.min(start + step, samples.length);
      for (let i = start; i < end; i += 1) {
        minimum = Math.min(minimum, samples[i]);
        maximum = Math.max(maximum, samples[i]);
      }
      context.fillRect(x, center + minimum * center * 0.88, 1, Math.max(1, (maximum - minimum) * center * 0.88));
    }

    lines.forEach((line, index) => {
      if (line.start === null || line.end === null || !audioPlayer.duration) return;
      const left = (line.start / audioPlayer.duration) * bounds.width;
      const right = (line.end / audioPlayer.duration) * bounds.width;
      context.fillStyle = index === selectedLine ? "rgba(199, 137, 61, .16)" : "rgba(35, 81, 125, 0.1)";
      context.fillRect(left, 0, Math.max(2, right - left), bounds.height);
      context.fillStyle = index === selectedLine ? "#bd813b" : "#435b88";
      context.fillRect(left, 0, 2, bounds.height);
      context.fillRect(Math.max(left, right - 2), 0, 2, bounds.height);
    });

    if (audioPlayer.duration) {
      const position = (audioPlayer.currentTime / audioPlayer.duration) * bounds.width;
      context.fillStyle = "#353f48";
      context.fillRect(position, 0, 1.5, bounds.height);
    }
    document.querySelector("#waveform-empty").classList.add("hidden");
  } else {
    document.querySelector("#waveform-empty").classList.remove("hidden");
  }
  drawLineWaveforms();
}

function drawLineWaveforms() {
  document.querySelectorAll(".line-waveform").forEach((lineCanvas, index) => {
    const bounds = lineCanvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;

    const scale = window.devicePixelRatio || 1;
    lineCanvas.width = Math.round(bounds.width * scale);
    lineCanvas.height = Math.round(bounds.height * scale);
    const lineContext = lineCanvas.getContext("2d");
    lineContext.setTransform(scale, 0, 0, scale, 0, 0);
    lineContext.clearRect(0, 0, bounds.width, bounds.height);

    const line = lines[index];
    if (!audioBuffer) {
      lineCanvas.classList.add("unavailable");
      return;
    }
    lineCanvas.classList.remove("unavailable");

    const samples = audioBuffer.getChannelData(0);
    const sampleRate = audioBuffer.sampleRate;
    const range = lineWaveformRange(index);
    const firstSample = Math.max(0, Math.floor(range.start * sampleRate));
    const lastSample = Math.min(samples.length, Math.ceil(range.end * sampleRate));
    const sampleCount = Math.max(1, lastSample - firstSample);
    const samplesPerPixel = Math.max(1, Math.ceil(sampleCount / bounds.width));
    const center = bounds.height / 2;
    lineContext.fillStyle = "#6f89a6";

    for (let x = 0; x < bounds.width; x += 1) {
      const first = firstSample + x * samplesPerPixel;
      const last = Math.min(lastSample, first + samplesPerPixel);
      if (first >= last) break;
      let minimum = 1;
      let maximum = -1;
      for (let sample = first; sample < last; sample += 1) {
        minimum = Math.min(minimum, samples[sample]);
        maximum = Math.max(maximum, samples[sample]);
      }
      lineContext.fillRect(
        x,
        center + minimum * center * 0.88,
        1,
        Math.max(1, (maximum - minimum) * center * 0.88),
      );
    }

    if (validLine(line)) {
      const selectionLeft = ((line.start - range.start) / (range.end - range.start)) * bounds.width;
      const selectionRight = ((line.end - range.start) / (range.end - range.start)) * bounds.width;
      lineContext.fillStyle = "rgba(199, 137, 61, .2)";
      lineContext.fillRect(selectionLeft, 0, Math.max(1, selectionRight - selectionLeft), bounds.height);
      lineContext.fillStyle = "#bd813b";
      lineContext.fillRect(selectionLeft, 0, 2, bounds.height);
      lineContext.fillRect(Math.max(selectionLeft, selectionRight - 2), 0, 2, bounds.height);
    }

    if (lineWaveformDrag?.index === index) {
      const dragLeft = ((Math.min(lineWaveformDrag.startTime, lineWaveformDrag.currentTime) - range.start)
        / (range.end - range.start)) * bounds.width;
      const dragRight = ((Math.max(lineWaveformDrag.startTime, lineWaveformDrag.currentTime) - range.start)
        / (range.end - range.start)) * bounds.width;
      lineContext.fillStyle = "rgba(199, 137, 61, .38)";
      lineContext.fillRect(dragLeft, 0, Math.max(1, dragRight - dragLeft), bounds.height);
    }

    if (audioPlayer.duration && audioPlayer.currentTime >= range.start && audioPlayer.currentTime <= range.end) {
      const playhead = ((audioPlayer.currentTime - range.start) / (range.end - range.start)) * bounds.width;
      lineContext.fillStyle = "#35483f";
      lineContext.fillRect(playhead, 0, 1.5, bounds.height);
    }
  });
}

function updatePreviewControls() {
  document.querySelectorAll(".line-preview-button").forEach((button) => {
    const index = Number(button.dataset.line);
    const line = lines[index];
    const isPlaying = previewingLine === index && !audioPlayer.paused;
    button.disabled = !audioFile || !validLine(line);
    button.textContent = isPlaying ? "❚❚" : "▶";
    button.setAttribute("aria-label", `${isPlaying ? "Pause" : "Play"} line ${index + 1}`);
  });
}

function playLinePreview(index, fromTime = null) {
  const line = lines[index];
  if (!audioFile || !validLine(line) || !Number.isFinite(audioPlayer.duration)) return;

  selectedLine = index;
  document.querySelectorAll(".line-card").forEach((card, cardIndex) => {
    card.classList.toggle("selected", cardIndex === selectedLine);
  });
  previewingLine = index;
  audioPlayer.currentTime = Math.max(line.start, Math.min(fromTime ?? line.start, line.end));
  updatePreviewControls();
  drawWaveform();
  audioPlayer.play().catch((error) => {
    previewingLine = null;
    updatePreviewControls();
    drawWaveform();
    showStatus(`Could not play line ${index + 1}: ${error.message}`, "error");
  });
}

function stopLinePreview() {
  previewingLine = null;
  audioPlayer.pause();
  updatePreviewControls();
  drawWaveform();
}

function onAudioTimeUpdate() {
  if (previewingLine !== null) {
    const line = lines[previewingLine];
    if (!validLine(line) || audioPlayer.currentTime >= line.end) {
      const clipEnd = line?.end;
      previewingLine = null;
      audioPlayer.pause();
      if (Number.isFinite(clipEnd)) audioPlayer.currentTime = clipEnd;
    }
    updatePreviewControls();
  }
  drawWaveform();
}

async function loadWaveform(file) {
  const decoder = new AudioContext();
  try {
    audioBuffer = await decoder.decodeAudioData(await file.arrayBuffer());
  } finally {
    await decoder.close();
  }
  drawWaveform();
}

audioInput.addEventListener("change", async () => {
  audioFile = audioInput.files?.[0] ?? null;
  previewingLine = null;
  audioPlayer.pause();
  lines = [];
  preparedDialogueText = null;
  selectedLine = 0;
  lineList.replaceChildren();
  document.querySelector("#editor").classList.add("hidden");
  uploadRow.append(autoSyncButton);
  autoSyncButton.innerHTML = 'Prepare &amp; auto-sync <span aria-hidden="true">✦</span>';
  updateExportState();
  audioBuffer = null;
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  if (!audioFile) return;
  if (audioFile.size > 100 * 1024 * 1024) {
    audioFile = null;
    audioInput.value = "";
    document.querySelector("#audio-name").textContent = "No audio selected";
    document.querySelector("#loaded-audio-title").textContent = "Dialogue audio";
    showStatus("The MP3 must be 100 MB or smaller.", "error");
    updateExportState();
    drawWaveform();
    return;
  }

  audioUrl = URL.createObjectURL(audioFile);
  audioPlayer.src = audioUrl;
  document.querySelector("#audio-name").textContent = audioFile.name;
  document.querySelector("#loaded-audio-title").textContent = audioFile.name;
  document.querySelector("#waveform-empty").classList.remove("hidden");
  try {
    await loadWaveform(audioFile);
    showStatus("MP3 loaded. Prepare and auto-sync the dialogue, then review each line's timing.", "success");
  } catch (error) {
    audioBuffer = null;
    showStatus(`The browser could not decode this MP3: ${error.message}`, "error");
  }
});

autoSyncButton.addEventListener("click", async () => {
  if (!audioFile) {
    showStatus("Choose the dialogue MP3 before preparing and syncing lines.", "error");
    return;
  }

  const dialogueText = document.querySelector("#dialogue-text").value;
  if (!lines.length || dialogueText !== preparedDialogueText) {
    const parsed = parseDialogue(dialogueText);
    if (!parsed.length) {
      showStatus("Enter dialogue text first. Put each sentence on its own line.", "error");
      return;
    }
    lines = parsed.map((sentence) => ({
      sentence,
      start: null,
      end: null,
      gloss: "",
      reading: "",
      ruby: "",
      dictionaryGloss: "",
      confidence: null,
      matched: null,
      manualTiming: false,
    }));
    preparedDialogueText = dialogueText;
    selectedLine = 0;
    document.querySelector("#editor").classList.remove("hidden");
    renderLines();
    editorActions.append(autoSyncButton);
    autoSyncButton.innerHTML = 'Auto-sync lines <span aria-hidden="true">✦</span>';
    document.querySelector("#editor").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  if (!audioFile || !lines.length || !audioPlayer.duration) {
    showStatus("Wait for the MP3 to finish loading before auto-syncing.", "error");
    return;
  }

  const dialogueLines = lines.map((line) => line.sentence);
  const headingCandidate = dialogueHeading && lines[0]?.sentence !== dialogueHeading
    ? dialogueHeading
    : null;
  const sourceLines = headingCandidate
    ? [headingCandidate, ...dialogueLines]
    : dialogueLines;
  const form = new FormData();
  form.append("audio", audioFile, audioFile.name);
  form.append("request_json", JSON.stringify({ lines: sourceLines, duration: audioPlayer.duration }));
  autoSyncButton.disabled = true;
  autoSyncButton.textContent = "Transcribing locally…";
  showStatus(
    "Transcribing Mandarin and matching the dialogue. The first run may take a few minutes while the local speech model downloads.",
    "info",
  );

  try {
    const response = await fetch("/api/align", { method: "POST", body: form });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Automatic sync failed.");
    if (lines.length !== dialogueLines.length || lines.some((line, index) => line.sentence !== dialogueLines[index])) {
      throw new Error("The dialogue changed during auto-sync. Run auto-sync again to use the updated text.");
    }
    if (!Array.isArray(result.matches) || result.matches.length > sourceLines.length) {
      throw new Error("Automatic sync returned invalid line timings. Restart the app and try again.");
    }

    const matchesByLine = new Map();
    result.matches.forEach((match) => {
      if (
        !match
        || typeof match !== "object"
        || !Number.isInteger(match.line)
        || match.line < 0
        || match.line >= sourceLines.length
        || matchesByLine.has(match.line)
      ) {
        throw new Error("Automatic sync returned invalid line timings. Restart the app and try again.");
      }
      if (
        Number.isFinite(match.start)
        && Number.isFinite(match.end)
        && match.end > match.start
        && (typeof match.matched_text !== "string" || !match.matched_text.trim())
      ) {
        throw new Error(
          "The sync server returned timings without recognized text. Stop any old Dialogue Workshop server and restart the app from its project folder.",
        );
      }
      matchesByLine.set(match.line, match);
    });

    const candidateMatches = sourceLines.map((_, index) => matchesByLine.get(index) ?? null);
    const alignedGroups = mergeLinesAtAudioPauses(sourceLines, candidateMatches);
    const includeHeading = Boolean(headingCandidate && hasValidMatch(alignedGroups[0]?.match));
    const dialogueGroupOffset = headingCandidate ? 1 : 0;
    const firstDialogueGroup = includeHeading ? 1 : dialogueGroupOffset;
    const syncedLines = alignedGroups.slice(firstDialogueGroup).map((group) => {
      const match = group.match;
      const sourceIndex = group.sourceIndices[0] - dialogueGroupOffset;
      const originalLine = lines[sourceIndex];
      const unchangedSingleLine = group.sourceIndices.length === 1
        && originalLine?.sentence === group.sentence;
      return {
        sentence: group.sentence,
        start: hasValidMatch(match) ? match.start : null,
        end: hasValidMatch(match) ? match.end : null,
        gloss: unchangedSingleLine ? originalLine.gloss : "",
        reading: unchangedSingleLine ? originalLine.reading : "",
        ruby: unchangedSingleLine ? originalLine.ruby : "",
        dictionaryGloss: unchangedSingleLine ? originalLine.dictionaryGloss : "",
        confidence: Number.isFinite(match?.confidence) ? match.confidence : 0,
        matched: hasValidMatch(match),
        manualTiming: false,
      };
    });
    if (includeHeading) {
      const match = alignedGroups[0].match;
      syncedLines.unshift({
        sentence: headingCandidate,
        start: match.start,
        end: match.end,
        gloss: "",
        reading: "",
        ruby: "",
        dictionaryGloss: "",
        confidence: Number.isFinite(match.confidence) ? match.confidence : 0,
        matched: true,
        manualTiming: false,
      });
    }
    lines = syncedLines;
    renderLines();
    const matched = lines.filter((line) => line.matched).length;
    const missed = lines.length - matched;
    showStatus(
      missed
        ? `Auto-sync matched ${matched} of ${lines.length} lines. Review the unmatched lines and drag across their waveforms to set their timings. Unspoken lesson headings and introductions are ignored.`
        : `Auto-sync matched all ${lines.length} lines. Review the timings and text-match scores before exporting.`,
      missed ? "info" : "success",
    );
  } catch (error) {
    showStatus(error.message, "error");
  } finally {
    autoSyncButton.disabled = false;
    autoSyncButton.innerHTML = 'Auto-sync lines <span aria-hidden="true">✦</span>';
  }
});

audioPlayer.addEventListener("loadedmetadata", () => {
  document.querySelector("#audio-duration").textContent = `Duration · ${formatTime(audioPlayer.duration)}`;
  updateExportState();
  drawWaveform();
});
audioPlayer.addEventListener("play", updatePreviewControls);
audioPlayer.addEventListener("pause", () => {
  if (previewingLine !== null) previewingLine = null;
  updatePreviewControls();
  drawWaveform();
});
audioPlayer.addEventListener("timeupdate", onAudioTimeUpdate);
audioPlayer.addEventListener("seeked", drawWaveform);
window.addEventListener("resize", drawWaveform);

canvas.addEventListener("click", (event) => {
  if (!audioPlayer.duration) return;
  previewingLine = null;
  const rect = canvas.getBoundingClientRect();
  audioPlayer.currentTime = ((event.clientX - rect.left) / rect.width) * audioPlayer.duration;
  updatePreviewControls();
  audioPlayer.play().catch((error) => showStatus(`Could not play audio: ${error.message}`, "error"));
});

vocabularyToggle.addEventListener("click", async () => {
  if (!vocabularyPreview.hidden) {
    setVocabularyPreviewMode(false);
    return;
  }

  const { entries, invalidLines } = parseVocabulary();
  if (invalidLines.length) {
    showStatus(`Add a Chinese word and its definition to vocabulary line${invalidLines.length === 1 ? "" : "s"} ${invalidLines.join(", ")}.`, "error");
    return;
  }
  if (!entries.length) {
    showStatus("Enter at least one vocabulary word and definition to preview.", "error");
    return;
  }

  vocabularyToggle.disabled = true;
  vocabularyToggle.textContent = "Generating ruby…";
  showStatus("Generating tone-colored vocabulary ruby locally.", "info");
  try {
    const response = await fetch("/api/vocabulary-fields", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        words: entries.map(({ word }) => word),
        pronunciations: entries.map(({ pronunciation }) => pronunciation),
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Vocabulary ruby generation failed.");
    if (!Array.isArray(result.words) || result.words.length !== entries.length) {
      throw new Error("The Chinese Support engine returned an incomplete set of vocabulary ruby.");
    }
    result.words.forEach((fields, index) => {
      if (!fields || typeof fields.ruby !== "string") {
        throw new Error(`The Chinese Support engine returned invalid ruby for vocabulary item ${index + 1}.`);
      }
    });
    vocabularyRubyByWord = new Map(
      entries.map(({ word }, index) => [word, result.words[index].ruby]),
    );
    generatedVocabularySignature = vocabularySignature(entries);
    renderVocabularyPreview(entries);
    setVocabularyPreviewMode(true);
    showStatus("Vocabulary submitted. Ruby and definitions are shown in the sidebar.", "success");
  } catch (error) {
    showStatus(error.message, "error");
  } finally {
    vocabularyToggle.disabled = false;
    if (vocabularyPreview.hidden) vocabularyToggle.textContent = "Show formatted vocabulary";
  }
});

generateFieldsButton.addEventListener("click", async () => {
  if (!lines.length) {
    showStatus("Prepare the dialogue lines before generating translations and study fields.", "error");
    return;
  }
  const { entries: vocabularyEntries, invalidLines } = parseVocabulary();
  if (invalidLines.length) {
    showStatus(`Add a Chinese word and its definition to vocabulary line${invalidLines.length === 1 ? "" : "s"} ${invalidLines.join(", ")}.`, "error");
    return;
  }
  generateFieldsButton.disabled = true;
  generateFieldsButton.textContent = "Generating fields locally…";
  showStatus(
    "Generating English translations, readings, ruby, and dictionary glosses locally. First use may download the local models and dictionary.",
    "info",
  );
  try {
    const lineTexts = lines.map((line) => line.sentence);
    const [translationResponse, studyFieldsResponse] = await Promise.all([
      fetch("/api/translations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lines: lineTexts }),
      }),
      fetch("/api/study-fields", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lines: lineTexts,
          vocabulary: vocabularyEntries.map(({ word }) => word),
          pronunciations: vocabularyEntries.map(({ pronunciation }) => pronunciation),
        }),
      }),
    ]);
    const [translationResult, studyFieldsResult] = await Promise.all([
      translationResponse.json(),
      studyFieldsResponse.json(),
    ]);
    if (!translationResponse.ok) {
      throw new Error(translationResult.detail || "Translation generation failed.");
    }
    if (!studyFieldsResponse.ok) {
      throw new Error(studyFieldsResult.detail || "Study field generation failed.");
    }
    if (!Array.isArray(translationResult.translations) || translationResult.translations.length !== lines.length) {
      throw new Error("The local translator returned an incomplete set of translations.");
    }
    if (!Array.isArray(studyFieldsResult.lines) || studyFieldsResult.lines.length !== lines.length) {
      throw new Error("The Chinese Support engine returned an incomplete set of study fields.");
    }
    if (!Array.isArray(studyFieldsResult.vocabulary) || studyFieldsResult.vocabulary.length !== vocabularyEntries.length) {
      throw new Error("The Chinese Support engine returned an incomplete set of vocabulary ruby.");
    }
    studyFieldsResult.lines.forEach((fields, index) => {
      if (
        !fields
        || typeof fields.reading !== "string"
        || typeof fields.ruby !== "string"
        || typeof fields.dictionary_gloss !== "string"
      ) {
        throw new Error(`The Chinese Support engine returned invalid fields for line ${index + 1}.`);
      }
      lines[index].gloss = translationResult.translations[index];
      lines[index].reading = fields.reading;
      lines[index].ruby = fields.ruby;
      lines[index].dictionaryGloss = fields.dictionary_gloss;
      lines[index].studyFieldsOpen = index === 0;
    });
    studyFieldsResult.vocabulary.forEach((fields, index) => {
      if (!fields || typeof fields.ruby !== "string") {
        throw new Error(`The Chinese Support engine returned invalid ruby for vocabulary item ${index + 1}.`);
      }
    });
    vocabularyRubyByWord = new Map(
      vocabularyEntries.map(({ word }, index) => [word, studyFieldsResult.vocabulary[index].ruby]),
    );
    generatedVocabularySignature = vocabularySignature(vocabularyEntries);
    if (!vocabularyPreview.hidden) renderVocabularyPreview(vocabularyEntries);
    renderLines();
    showStatus(
      vocabularyEntries.length
        ? "English translations, readings, ruby, and dictionary glosses generated locally. Matched vocabulary will be included in the line export."
        :         "English translations, readings, ruby, and dictionary glosses generated locally. Expand each line to review or edit its fields.",
      "success",
    );
  } catch (error) {
    showStatus(error.message, "error");
  } finally {
    generateFieldsButton.disabled = false;
    generateFieldsButton.innerHTML = 'Generate translations &amp; study fields <span aria-hidden="true">↗</span>';
  }
});

exportButton.addEventListener("click", async () => {
  if (!audioFile || !allLinesTimed()) return;
  const { entries: vocabularyEntries, invalidLines } = parseVocabulary();
  if (invalidLines.length) {
    showStatus(`Add a Chinese word and its definition to vocabulary line${invalidLines.length === 1 ? "" : "s"} ${invalidLines.join(", ")}.`, "error");
    return;
  }
  if (
    vocabularyEntries.length
    && (
      generatedVocabularySignature !== vocabularySignature(vocabularyEntries)
      || vocabularyEntries.some(({ word }) => !vocabularyRubyByWord.has(word))
    )
  ) {
    showStatus("Generate translations & study fields after entering or changing vocabulary so WordRuby can be included in the export.", "error");
    return;
  }
  exportButton.disabled = true;
  exportButton.textContent = "Preparing clips…";
  try {
    const title = audioFile.name.replace(/\.mp3$/i, "");
    const manifest = {
      title,
      source_folder: sourceFolderInput.value.trim(),
      duration: audioPlayer.duration,
      lines: lines.map((line) => ({
        sentence: line.sentence,
        start: line.start,
        end: line.end,
        gloss: line.gloss,
        reading: line.reading,
        ruby: line.ruby,
        dictionary_gloss: line.dictionaryGloss,
        ...vocabularyFieldsForLine(line.sentence, vocabularyEntries),
      })),
    };
    const body = new FormData();
    body.append("audio", audioFile, audioFile.name);
    body.append("manifest", JSON.stringify(manifest));
    const response = await fetch("/api/export", { method: "POST", body });
    if (!response.ok) {
      const result = await response.json();
      throw new Error(result.detail || "Clip export failed.");
    }
    const blob = await response.blob();
    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = `${title.replace(/[^\p{L}\p{N}_.-]+/gu, "-") || "dialogue"}-dialogue.zip`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
    showStatus("Your ZIP is ready. It includes an MP3 for each line plus dialogue JSON and CSV.", "success");
  } catch (error) {
    showStatus(error.message, "error");
  } finally {
    exportButton.innerHTML = 'Export line clips <span aria-hidden="true">↓</span>';
    updateExportState();
  }
});

audioPlayer.addEventListener("loadedmetadata", updateExportState);
drawWaveform();
