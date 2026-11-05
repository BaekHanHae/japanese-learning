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
    const meanings = (item.meanings || []).slice(0, 4).join(" · ") || "뜻 정보 없음";
    const example = item.example_ja
      ? `<p class="example jp">${esc(item.example_ja)}</p><p class="example-en">${esc(item.example_en)}</p>`
      : "";
    return `<article class="card jlpt-card">
      <div class="card-body">
        <p class="jlpt-word jp">${esc(item.word)}</p>
        <div class="jlpt-detail" hidden>
          <p class="meaning">${esc(item.reading)} · ${esc(meanings)}</p>
          ${example}
        </div>
      </div>
      <div class="actions">
        <button class="save" data-reveal>뜻 보기</button>
        <button class="save" data-speak="${esc(item.reading)}" title="소리로 듣기" aria-label="소리로 듣기">🔊</button>
        ${item.jmdict_id ? `<button class="save" data-save-jlpt="${esc(item.jmdict_id)}">＋ 저장</button>` : ""}
      </div>
    </article>`;
  }

  async function load() {
    if (busy) return;
    busy = true;
    const level = $("#jlptLevel").value;
    try {
      const data = await api(`/api/jlpt?level=${encodeURIComponent(level)}&exclude=${encodeURIComponent(seen.slice(-40).join(","))}`);
      if (!data.items.length) {
        panel.innerHTML = '<div class="empty"><strong>단어를 찾지 못했어요</strong><p>다른 단계를 선택해 보세요.</p></div>';
        return;
      }
      seen = [...seen, ...data.items.map((item) => item.id)].slice(-80);
      panel.innerHTML = data.items.map(card).join("");
      $("#resultCount").textContent = `${data.items.length}단어 · ${level} (OpenJLPT 기준)`;
    } catch (error) {
      panel.innerHTML = `<div class="error">${esc(error.message)}</div>`;
    } finally {
      busy = false;
    }
  }

  panel.addEventListener("click", async (event) => {
    const speak = event.target.closest("[data-speak]");
    if (speak) {
      window.kotobaSpeak(speak.dataset.speak);
      return;
    }
    const reveal = event.target.closest("[data-reveal]");
    if (reveal) {
      const detail = reveal.closest(".card").querySelector(".jlpt-detail");
      detail.hidden = !detail.hidden;
      reveal.textContent = detail.hidden ? "뜻 보기" : "뜻 숨기기";
      return;
    }
    const save = event.target.closest("[data-save-jlpt]");
    if (save) {
      save.disabled = true;
      try {
        await post("/api/save", { id: save.dataset.saveJlpt });
        save.textContent = "저장됨";
        save.classList.add("saved");
      } catch (error) {
        save.disabled = false;
        alert(error.message);
      }
    }
  });

  document.querySelectorAll('.nav[data-view="jlpt"]').forEach((button) => {
    button.addEventListener("click", () => {
      $("#jlptBar").style.display = "flex";
      $("#browseSentinel").style.display = "none";
      $("#loadMore").style.display = "none";
      $("#studyPanel").style.display = "none";
      $("#wordFilters").style.display = "none";
      $("#materialFilters").style.display = "none";
      $("#materialSearch").style.display = "none";
      $("#readingBar").style.display = "none";
      load();
    });
  });

  document.querySelectorAll('.nav:not([data-view="jlpt"])').forEach((button) => {
    button.addEventListener("click", () => {
      $("#jlptBar").style.display = "none";
    });
  });

  $("#jlptNext").addEventListener("click", load);
  $("#jlptLevel").addEventListener("change", () => {
    seen = [];
    load();
  });
})();
