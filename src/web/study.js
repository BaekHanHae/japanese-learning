(() => {
  const $ = (selector) => document.querySelector(selector);
  const escStudy = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => {
    if (c === "&") return "&amp;";
    if (c === "<") return "&lt;";
    if (c === ">") return "&gt;";
    if (c === '"') return "&quot;";
    return "&#39;";
  });
  const labels = {
    word_flashcard: "단어 플래시카드",
    word_typing: "단어 입력",
    sentence_typing: "문장 번역 입력",
    japanese_copy_typing: "일본어 보고 입력",
    dialogue_typing: "대화 입력"
  };
  let item = null;
  let completed = false;
  let revealed = false;
  let checking = false;
  let lastCorrect = null;
  let lastInput = "";
  let latestStats = {};
  const session = { done: 0, checked: 0, correct: 0, target: 20 };
  const miscNames = {
    abbr: "약어", arch: "고어", col: "구어", fam: "반말", female: "여성어",
    hon: "존경", id: "관용", male: "남성어", on_mim: "의성어", pol: "공손",
    proverb: "속담", sl: "속어", uk: "보통 가나", vulg: "비어"
  };
  const fieldNames = {
    biol: "생물", chem: "화학", comp: "컴퓨터", econ: "경제", food: "음식",
    law: "법", ling: "언어", math: "수학", med: "의학", music: "음악",
    physics: "물리", sports: "스포츠"
  };
  const tagName = (tag, names) => names[tag] || tag;

  const post = (path, body) => api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });

  function emptyStudy(title, body) {
    return `<div class="empty"><strong>${escStudy(title)}</strong><p>${escStudy(body)}</p></div>`;
  }

  function showError(message) {
    const feedback = $("#studyFeedback");
    const html = `<div class="error">${escStudy(message)}</div>`;
    if (feedback) feedback.innerHTML = html;
    else $("#studyTask").innerHTML = html;
  }

  async function counts() {
    try {
      const data = await api("/api/study/overview");
      const c = data.counts;
      $("#studyCounts").textContent = `학습 중 ${c.word_learning || 0}개 단어 · ${c.material_learning || 0}개 자료 / 완료 ${c.word_mastered || 0}개 단어 · ${c.material_mastered || 0}개 자료`;
      const stats = data.stats || {};
      latestStats = stats;
      const tomorrow = Object.values(stats.forecast || {})[1] || 0;
      const retention = Math.round(((stats.retention?.recognition?.recall || 0) * 100));
      $("#studyStats").textContent = [
        `오늘 복습 ${stats.reviews_today || 0}/${stats.review_cap || 80}`,
        `신규 ${stats.new_today || 0}/${stats.new_cap || 15}`,
        `연속 ${stats.streak_days || 0}일`,
        `내일 ${tomorrow}개`,
        retention ? `인식 유지 ${retention}%` : ""
      ].filter(Boolean).join(" · ");
      $("#dueCount").textContent = Object.values(data.due).reduce((sum, n) => sum + n, 0);
    } catch (_error) {
      $("#studyCounts").textContent = "";
    }
  }

  function renderTask() {
    const root = $("#studyTask");
    if (!item) {
      root.innerHTML = completed
        ? emptyStudy("완료한 항목이 없어요", "학습을 마친 항목이 여기에 표시됩니다.")
        : emptyStudy("이 방식으로 연습할 항목이 없어요", "단어장에 단어를 저장하거나, 문장·대화 자료를 저장해 주세요.");
      return;
    }
    const mode = $("#studyMode").value;
    const word = item.type === "word";
    const prompt = mode === "word_flashcard"
      ? item.front
      : mode === "japanese_copy_typing"
        ? item.japanese
        : word ? item.glosses.slice(0, 3).join(" · ") : item.english;
    const context = (item.context_turns || []).map((turn) => `<div class="studycontext"><small>${escStudy(turn.speaker)}</small><p class="jp">${escStudy(turn.japanese)}</p><small>${escStudy(turn.english)}</small><button class="speak small" data-speak="${escStudy(turn.japanese)}" title="대사 듣기" aria-label="대사 듣기">🔊</button></div>`).join("");
    const setting = mode === "dialogue_typing" ? `<p class="meaning">${escStudy(item.context)} · 화자: ${escStudy(item.metadata?.ja_speaker || "정보 없음")}</p>` : "";
    const typing = mode !== "word_flashcard";
    const canSpeak = mode === "word_flashcard" || mode === "japanese_copy_typing";
    const speakText = word ? item.readings[0] || item.front : item.japanese;
    const due = item.is_due ? '<span class="badge due">복습할 차례</span>' : '<span class="badge">미리 연습</span>';
    root.innerHTML = `<div class="studycard">
      <div class="studycard-head"><span class="study-mode">${escStudy(labels[mode])}</span>${due}</div>
      ${setting}${context}
      <p class="meaning">${escStudy(item.prompt || "")}</p>
      <div class="studyjp-row">
        <div class="studyjp">${escStudy(prompt || "뜻 정보 없음")}</div>
        ${canSpeak ? `<button class="speak" data-speak="${escStudy(speakText)}" title="소리로 듣기" aria-label="소리로 듣기">🔊</button>` : ""}
      </div>
      ${typing ? `<label class="sr-only" for="studyAnswer">답 입력</label><input id="studyAnswer" class="studyanswer" autocomplete="off" placeholder="일본어 입력 · Enter 또는 Control+Enter">` : ""}
      ${mode === "japanese_copy_typing" ? '<p class="hint-inline">Enter 또는 Control+Enter로 제출합니다. 맞으면 다음 문장으로 넘어가요.</p>' : ""}
      <div class="studybuttons">
        ${typing ? '<button class="primary" id="checkStudyAnswer">답 확인</button>' : '<button class="primary" id="revealStudyAnswer">정답 보기</button>'}
        <button class="save" id="masterStudyItem">${completed ? "다시 학습하기" : "학습 완료"}</button>
      </div>
      <div id="studyFeedback" role="status" aria-live="polite">${revealed ? feedbackHtml() : ""}</div>
    </div>`;
    $("#checkStudyAnswer")?.addEventListener("click", check);
    $("#studyAnswer")?.addEventListener("keydown", (event) => {
      const enter = event.key === "Enter";
      if (enter && (event.ctrlKey || (!event.isComposing && event.keyCode !== 229))) {
        event.preventDefault();
        check();
      }
    });
    if (mode === "japanese_copy_typing") $("#studyAnswer")?.focus();
    $("#revealStudyAnswer")?.addEventListener("click", () => {
      revealed = true;
      renderTask();
    });
    $("#masterStudyItem")?.addEventListener("click", async () => {
      try {
        await post("/api/study/master", { type: item.type, id: item.id, mode, mastered: !completed });
        await counts();
        await (completed ? showCompleted() : loadNext());
      } catch (error) {
        showError(error.message);
      }
    });
    attachRatings();
    if (revealed) refreshPitch();
  }

  function highlight(text, forms) {
    let html = escStudy(text);
    for (const form of [...forms].sort((a, b) => b.length - a.length)) {
      const safe = escStudy(form);
      if (!safe) continue;
      const at = html.indexOf(safe);
      if (at >= 0) {
        return `${html.slice(0, at)}<mark>${safe}</mark>${html.slice(at + safe.length)}`;
      }
    }
    return html;
  }

  function diffHtml(input, expected) {
    if (!input || !expected) return "";
    let head = 0;
    while (head < input.length && head < expected.length && input[head] === expected[head]) head += 1;
    let tail = 0;
    while (
      tail < input.length - head &&
      tail < expected.length - head &&
      input[input.length - 1 - tail] === expected[expected.length - 1 - tail]
    ) tail += 1;
    const cut = input.length - tail;
    const wantCut = expected.length - tail;
    return `<div class="diff"><p class="feedback-label">내 답</p>
      <p class="diff-line">${escStudy(input.slice(0, head))}<del>${escStudy(input.slice(head, cut))}</del>${escStudy(input.slice(cut))}</p>
      <p class="diff-line">${escStudy(expected.slice(0, head))}<ins>${escStudy(expected.slice(head, wantCut))}</ins>${escStudy(expected.slice(wantCut))}</p></div>`;
  }

  function feedbackHtml(result) {
    const word = item.type === "word";
    const answer = word
      ? `<span class="jp">${escStudy(item.front)}</span><br><small>${item.readings.map((reading) => escStudy(reading)).join(" · ")}</small><br>${item.glosses.slice(0, 5).map(escStudy).join(" · ")}`
      : `<span class="jp">${renderFurigana(item.japanese)}</span><br><small>${escStudy(item.reading || "")}</small><br>${escStudy(item.english)}<br><small>${escStudy(item.source)} · ${escStudy(item.license)} · <a href="${escStudy(item.source_url)}" target="_blank" rel="noopener">출처</a></small>`;
    const verdict = result
      ? result.correct
        ? '<p class="verdict ok">맞았어요.</p>'
        : '<p class="verdict no">원문과 달라요. 직접 비교해 보세요.</p>'
      : "";
    const state = result ? (result.correct ? "is-correct" : "is-wrong") : "";
    const tags = word
      ? [
          ...(item.misc || []).map((tag) => tagName(tag, miscNames)),
          ...(item.fields || []).map((tag) => tagName(tag, fieldNames))
        ]
      : [];
    const tagHtml = tags.length
      ? `<div class="tags">${tags.map((tag) => `<span class="tag">${escStudy(tag)}</span>`).join("")}</div>`
      : "";
    const examples = word && item.examples?.length
      ? `<div class="examples"><p class="feedback-label">예문</p>${item.examples.map((example) => `<p class="example jp">${highlight(example.japanese, item.forms)}</p><p class="example-en">${escStudy(example.english || "")}</p>`).join("")}</div>`
      : "";
    const diff = result && !result.correct ? diffHtml(lastInput, result.accepted[0] || "") : "";
    const pitch = word
      ? `<p class="pitch" data-pitch-word="${escStudy(item.forms[0] || "")}" data-pitch-reading="${escStudy(item.readings[0] || "")}" hidden></p>`
      : "";
    const speak = `<button class="speak small" data-speak="${escStudy(word ? item.readings[0] || item.front : item.japanese)}" title="소리로 듣기" aria-label="소리로 듣기">🔊</button>`;
    return `<div class="studyfeedback ${state}">${verdict}<p class="feedback-label">정답 예시 ${speak}</p>${answer}${pitch}${tagHtml}${examples}${diff}<div class="studybuttons">${ratings()}</div></div>`;
  }

  async function refreshPitch() {
    const target = document.querySelector("[data-pitch-word]");
    if (!target || target.dataset.loaded) return;
    target.dataset.loaded = "1";
    try {
      const data = await api(`/api/pitch?word=${encodeURIComponent(target.dataset.pitchWord)}&reading=${encodeURIComponent(target.dataset.pitchReading)}`);
      if (data.accents?.length) {
        target.textContent = `피치 ${data.accents.join(" · ")} (0=평평, n=끝에서 하강)`;
        target.hidden = false;
      }
    } catch (_error) {
      // Pitch data is optional; the card remains usable without it.
    }
  }

  function ratings() {
    return [["again", "다시 (10분 후)"], ["hard", "어려웠어요"], ["good", "알았어요"], ["easy", "쉬웠어요"]]
      .map(([id, text]) => `<button class="save" data-rating="${id}">${text}</button>`)
      .join("");
  }

  async function check() {
    if (!item || checking) return;
    checking = true;
    const mode = $("#studyMode").value;
    lastInput = $("#studyAnswer").value;
    try {
      const result = await post("/api/study/check", {
        type: item.type,
        id: item.id,
        mode,
        answer: $("#studyAnswer").value
      });
      lastCorrect = result.correct;
      if (mode === "japanese_copy_typing") {
        if (result.correct) {
          $("#studyFeedback").innerHTML = '<div class="studyfeedback is-correct" role="status">정답입니다. 다음 문장으로 넘어갑니다.</div>';
          $("#studyAnswer").disabled = true;
          await post("/api/study/review", { type: item.type, id: item.id, mode, rating: "good", correct: true });
          session.done += 1;
          session.checked += 1;
          session.correct += 1;
          await loadNext();
          $("#studyAnswer")?.focus();
          counts();
        } else {
          $("#studyFeedback").innerHTML = `<div class="studyfeedback is-wrong" role="status">아직 원문과 달라요. 고쳐서 다시 Enter를 누르세요.${diffHtml(lastInput, item.japanese)}</div>`;
          $("#studyAnswer").focus();
          $("#studyAnswer").select();
        }
        return;
      }
      revealed = true;
      $("#studyFeedback").innerHTML = feedbackHtml(result);
      attachRatings();
      refreshPitch();
    } catch (error) {
      showError(error.message);
    } finally {
      checking = false;
    }
  }

  function attachRatings() {
    document.querySelectorAll("[data-rating]").forEach((button) => {
      button.addEventListener("click", async () => {
        const wasCompleted = completed;
        button.disabled = true;
        try {
          await post("/api/study/review", {
            type: item.type,
            id: item.id,
            mode: $("#studyMode").value,
            rating: button.dataset.rating,
            correct: lastCorrect
          });
          session.done += 1;
          if (lastCorrect !== null) {
            session.checked += 1;
            session.correct += lastCorrect ? 1 : 0;
          }
          revealed = false;
          await counts();
          await (wasCompleted ? showCompleted() : loadNext());
        } catch (error) {
          button.disabled = false;
          showError(error.message);
        }
      });
    });
  }

  function renderSummary() {
    const s = session;
    const accuracy = s.checked ? Math.round((s.correct / s.checked) * 100) : null;
    const capped =
      (latestStats.reviews_today || 0) >= (latestStats.review_cap || 80);
    const tomorrow = Object.values(latestStats.forecast || {})[1] || 0;
    const detail = [
      accuracy === null ? "" : `입력 문제 정답률 ${accuracy}%`,
      tomorrow ? `내일 예정 ${tomorrow}개` : ""
    ].filter(Boolean).join(" · ");
    $("#studyTask").innerHTML = emptyStudy(
      capped ? "오늘 목표를 채웠어요" : s.done ? "오늘 세션을 마쳤어요" : "지금 복습할 항목이 없어요",
      capped
        ? `복습 ${latestStats.review_cap || 80}개를 모두 끝냈습니다. ${detail}`
        : s.done
          ? `${s.done}개를 학습했습니다. ${detail}`
          : "다음 예정이 되면 다시 나타납니다. 다른 학습 방식을 선택해 보세요."
    );
  }

  async function loadNext() {
    completed = false;
    try {
      const data = await api(`/api/study/next?${new URLSearchParams({ mode: $("#studyMode").value })}`);
      item = data.item;
      revealed = false;
      lastCorrect = null;
      lastInput = "";
      if (item) renderTask();
      else renderSummary();
    } catch (error) {
      item = null;
      $("#studyTask").innerHTML = `<div class="error">${escStudy(error.message)}</div>`;
      $("#studyCounts").textContent = "";
    }
  }

  async function showCompleted() {
    completed = true;
    try {
      const data = await api(`/api/study/next?${new URLSearchParams({ mode: $("#studyMode").value, completed: "1" })}`);
      item = data.item;
      revealed = false;
      renderTask();
    } catch (error) {
      item = null;
      $("#studyTask").innerHTML = `<div class="error">${escStudy(error.message)}</div>`;
    }
  }

  document.querySelectorAll('.nav[data-view="study"]').forEach((button) => button.addEventListener("click", async () => {
    $("#heading").textContent = "학습하기";
    $("#resultCount").textContent = "";
    $("#results").style.display = "none";
    $("#studyPanel").style.display = "block";
    $("#browseSentinel").style.display = "none";
    $("#loadMore").style.display = "none";
    $("#wordFilters").style.display = "none";
    $("#materialFilters").style.display = "none";
    $("#materialSearch").style.display = "none";
    session.done = 0;
    session.checked = 0;
    session.correct = 0;
    await counts();
    await loadNext();
  }));

  document.querySelectorAll('.nav:not([data-view="study"])').forEach((button) => button.addEventListener("click", () => {
    $("#studyPanel").style.display = "none";
    $("#results").style.display = "block";
    $("#browseSentinel").style.display = "block";
  }));

  $("#practiceNext").addEventListener("click", loadNext);
  $("#showCompleted").addEventListener("click", showCompleted);
  $("#studyMode").addEventListener("change", () => (completed ? showCompleted() : loadNext()));
  $("#studyTask").addEventListener("click", (event) => {
    const button = event.target.closest("[data-speak]");
    if (button) window.kotobaSpeak(button.dataset.speak);
  });
})();
