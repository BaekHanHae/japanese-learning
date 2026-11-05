(() => {
  const $ = (selector) => document.querySelector(selector);
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => {
    if (c === "&") return "&amp;";
    if (c === "<") return "&lt;";
    if (c === ">") return "&gt;";
    if (c === '"') return "&quot;";
    return "&#39;";
  });
  const panel = $("#results");
  let seen = [];
  let busy = false;

  const post = (path, body) => api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });

  function card(item) {
    const tokens = item.tokens.map((token) => token.id
      ? `<button class="token" data-word="${esc(token.id)}" data-surface="${esc(token.text)}">${esc(token.text)}</button>`
      : `<span>${esc(token.text)}</span>`).join("");
    const level = item.level ? `<span class="tag">${esc(item.level)} 참고</span>` : "";
    return `<article class="card reading-card">
      <div class="card-body">
        <p class="reading-jp jp">${tokens}</p>
        <p class="meaning reading-en" hidden>${esc(item.english)}</p>
        <div class="tags"><span class="tag">${esc(item.source)}</span>${level}</div>
        <div class="tokeninfo" hidden></div>
      </div>
      <div class="actions">
        <button class="save" data-speak="${esc(item.japanese)}" title="소리로 듣기" aria-label="소리로 듣기">🔊</button>
        <button class="save" data-translation>해석</button>
        <button class="save" data-save-sentence="${esc(item.id)}">＋ 문장 저장</button>
      </div>
    </article>`;
  }

  async function load() {
    if (busy) return;
    busy = true;
    const level = $("#readingLevel").value;
    try {
      const data = await api(`/api/reading?level=${encodeURIComponent(level)}&exclude=${encodeURIComponent(seen.slice(-30).join(","))}`);
      if (!data.items.length) {
        panel.innerHTML = '<div class="empty"><strong>문장을 찾지 못했어요</strong><p>다른 단계를 선택하거나 다음 문장을 눌러 보세요.</p></div>';
        return;
      }
      seen = [...seen, ...data.items.map((item) => item.id)].slice(-60);
      panel.innerHTML = data.items.map(card).join("");
      $("#resultCount").textContent = `${data.items.length}문장 · 모르는 단어를 눌러 보세요`;
    } catch (error) {
      panel.innerHTML = `<div class="error">${esc(error.message)}</div>`;
    } finally {
      busy = false;
    }
  }

  async function showWord(button, info) {
    button.disabled = true;
    const surface = button.dataset.surface || button.textContent.trim();
    try {
      const data = await api(`/api/word?id=${encodeURIComponent(button.dataset.word)}&surface=${encodeURIComponent(surface)}`);
      const item = data.item;
      const alternatives = (data.alternatives || []).filter((alt) => alt.id !== item.id);
      const altHtml = alternatives.length
        ? `<div class="altwords"><span>다른 뜻</span>${alternatives.map((alt) => `<button class="save compact" data-word="${esc(alt.id)}" data-surface="${esc(surface)}">${esc(alt.kanji[0] || alt.readings[0])}</button>`).join("")}</div>`
        : "";
      const pitch = item.pitch?.length
        ? `<p class="pitch">피치 ${esc(item.pitch.join(" · "))}</p>`
        : "";
      const kanji = item.kanji.length > 3
        ? `${item.kanji.slice(0, 3).join("、")} 외 ${item.kanji.length - 3}`
        : item.kanji.join("、");
      info.hidden = false;
      info.innerHTML = `<p class="jp">${esc(kanji || item.readings.join("、"))}</p>
        <p class="meaning">${esc(item.readings.join("、"))} · ${esc(item.glosses.slice(0, 3).join(" · ") || "뜻 정보 없음")}</p>
        ${pitch}
        ${altHtml}
        <div class="studybuttons"><button class="save ${item.saved ? "saved" : ""}" data-save-word="${esc(item.id)}">${item.saved ? "저장됨" : "＋ 단어 저장"}</button>
        <button class="save" data-speak="${esc(item.readings[0] || surface)}" title="소리로 듣기" aria-label="소리로 듣기">🔊</button></div>`;
    } catch (error) {
      info.hidden = false;
      info.innerHTML = `<div class="error">${esc(error.message)}</div>`;
    } finally {
      button.disabled = false;
    }
  }

  panel.addEventListener("click", async (event) => {
    const speak = event.target.closest("[data-speak]");
    if (speak) {
      window.kotobaSpeak(speak.dataset.speak);
      return;
    }
    const token = event.target.closest("[data-word]");
    if (token) {
      await showWord(token, token.closest(".card-body").querySelector(".tokeninfo"));
      return;
    }
    const saveWord = event.target.closest("[data-save-word]");
    if (saveWord) {
      saveWord.disabled = true;
      try {
        await post("/api/save", { id: saveWord.dataset.saveWord });
        saveWord.textContent = "저장됨";
        saveWord.classList.add("saved");
      } catch (error) {
        saveWord.disabled = false;
        alert(error.message);
      }
      return;
    }
    const translation = event.target.closest("[data-translation]");
    if (translation) {
      const line = translation.closest(".card").querySelector(".reading-en");
      line.hidden = !line.hidden;
      translation.textContent = line.hidden ? "해석" : "해석 숨기기";
      return;
    }
    const saveSentence = event.target.closest("[data-save-sentence]");
    if (saveSentence) {
      saveSentence.disabled = true;
      try {
        await post("/api/materials/save", { id: saveSentence.dataset.saveSentence });
        saveSentence.textContent = "저장됨";
        saveSentence.classList.add("saved");
      } catch (error) {
        saveSentence.disabled = false;
        alert(error.message);
      }
    }
  });

  document.querySelectorAll('.nav[data-view="reading"]').forEach((button) => {
    button.addEventListener("click", () => {
      $("#readingBar").style.display = "flex";
      panel.style.display = "block";
      $("#browseSentinel").style.display = "none";
      $("#loadMore").style.display = "none";
      $("#studyPanel").style.display = "none";
      $("#wordFilters").style.display = "none";
      $("#materialFilters").style.display = "none";
      $("#materialSearch").style.display = "none";
      $("#heading").textContent = "읽기";
      load();
    });
  });

  document.querySelectorAll('.nav:not([data-view="reading"])').forEach((button) => {
    button.addEventListener("click", () => {
      $("#readingBar").style.display = "none";
    });
  });

  $("#readingNext").addEventListener("click", load);
  $("#readingLevel").addEventListener("change", () => {
    seen = [];
    load();
  });
})();
