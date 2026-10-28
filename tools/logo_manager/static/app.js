(() => {
  "use strict";

  const state = {
    brands: [],
    query: "",
    size: localStorage.getItem("logoManager.size") || "normal",
    onlyMissing: false,
    detailSlug: null,
    pendingFile: null,
  };

  const $ = (selector) => document.querySelector(selector);

  const grid = $("#grid");
  const summary = $("#summary");
  const searchInput = $("#search");
  const emptyState = $("#empty-state");
  const onlyMissingInput = $("#only-missing");
  const sizeButtons = Array.from(document.querySelectorAll(".size-control button"));

  const detailModal = $("#detail-modal");
  const detailPreview = detailModal.querySelector(".detail-preview");
  const detailImg = $("#detail-img");
  const detailName = $("#detail-name");
  const detailSlug = $("#detail-slug");
  const detailReplace = $("#detail-replace");
  const detailRemoveLogo = $("#detail-remove-logo");
  const detailDelete = $("#detail-delete");
  const detailFile = $("#detail-file");

  const createModal = $("#create-modal");
  const createForm = $("#create-form");
  const createName = $("#create-name");
  const createDrop = $("#create-drop");
  const createPreview = $("#create-preview");
  const createHint = $("#create-hint");
  const createFile = $("#create-file");
  const createSubmit = $("#create-submit");

  const toasts = $("#toasts");

  // ---------------------------------------------------------------- utils

  const normalize = (value) =>
    (value || "")
      .toString()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "");

  const cssEscape = (value) =>
    window.CSS && CSS.escape ? CSS.escape(value) : value.replace(/[^a-zA-Z0-9_-]/g, "\\$&");

  async function api(url, options = {}) {
    const response = await fetch(url, options);
    let data = null;
    try {
      data = await response.json();
    } catch {
      /* respuesta sin cuerpo JSON */
    }
    if (!response.ok) {
      throw new Error((data && data.error) || `Error ${response.status}`);
    }
    return data;
  }

  function toast(message, type = "info") {
    const node = document.createElement("div");
    node.className = `toast ${type}`;
    node.textContent = message;
    toasts.appendChild(node);
    setTimeout(() => node.remove(), 4200);
  }

  function debounce(fn, delay) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), delay);
    };
  }

  // ---------------------------------------------------------------- render

  function matchesFilters(brand) {
    if (state.onlyMissing && brand.hasLogo) return false;
    const query = normalize(state.query);
    if (!query) return true;
    return normalize(brand.name).includes(query) || normalize(brand.slug).includes(query);
  }

  function updateSummary(visibleCount) {
    const total = state.brands.length;
    const missing = state.brands.filter((brand) => !brand.hasLogo).length;
    const suffix = `${missing} sin logo`;
    summary.textContent =
      visibleCount === total ? `${total} marcas · ${suffix}` : `${visibleCount} de ${total} marcas · ${suffix}`;
  }

  function logoSource(brand) {
    const variants = brand.variants || {};
    // Las tarjetas grandes usan la variante de mayor resolución para verse nítidas
    const order =
      state.size === "small"
        ? ["thumb", "optimized", "original"]
        : ["optimized", "thumb", "original"];
    for (const name of order) {
      if (variants[name]) return variants[name];
    }
    return null;
  }

  function buildCard(brand) {
    const card = document.createElement("article");
    card.className = "card";
    card.dataset.slug = brand.slug;
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.title = brand.hasLogo ? `Editar ${brand.name}` : `Agregar logo a ${brand.name}`;

    const box = document.createElement("div");
    box.className = "card-logo";
    const source = logoSource(brand);

    if (source) {
      const img = document.createElement("img");
      img.src = source.url;
      img.alt = `Logo de ${brand.name}`;
      img.loading = "lazy";
      img.decoding = "async";
      if (source.width) img.width = source.width;
      if (source.height) img.height = source.height;
      img.addEventListener("error", () => {
        box.classList.add("empty");
        box.textContent = "Sin logo";
      });
      box.appendChild(img);
    } else {
      box.classList.add("empty");
      box.textContent = "Sin logo";
    }

    const name = document.createElement("div");
    name.className = "card-name";
    name.textContent = brand.name;
    name.title = `${brand.name} (${brand.slug})`;

    card.append(box, name);

    card.addEventListener("click", () => openDetail(brand.slug));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openDetail(brand.slug);
      }
    });

    card.addEventListener("dragover", (event) => {
      event.preventDefault();
      card.classList.add("drop-target");
    });
    card.addEventListener("dragleave", () => card.classList.remove("drop-target"));
    card.addEventListener("drop", (event) => {
      event.preventDefault();
      card.classList.remove("drop-target");
      const file = event.dataTransfer?.files?.[0];
      if (file) replaceLogo(brand.slug, file);
    });

    return card;
  }

  function renderGrid() {
    const visible = state.brands.filter(matchesFilters);
    const fragment = document.createDocumentFragment();
    for (const brand of visible) fragment.appendChild(buildCard(brand));
    grid.replaceChildren(fragment);
    emptyState.hidden = visible.length > 0;
    updateSummary(visible.length);
  }

  function applyBrandUpdate(brand) {
    const index = state.brands.findIndex((item) => item.slug === brand.slug);
    if (index >= 0) state.brands[index] = brand;
    else state.brands.push(brand);
    state.brands.sort((a, b) => a.name.localeCompare(b.name, "es", { sensitivity: "base" }));
    renderGrid();
  }

  function markBusy(slug, busy) {
    const card = grid.querySelector(`[data-slug="${cssEscape(slug)}"]`);
    if (card) card.classList.toggle("busy", busy);
  }

  // ---------------------------------------------------------------- modals

  function openModal(modal) {
    modal.hidden = false;
  }

  function closeModal(modal) {
    modal.hidden = true;
  }

  function openDetail(slug) {
    const brand = state.brands.find((item) => item.slug === slug);
    if (!brand) return;

    state.detailSlug = slug;
    state.pendingFile = null;
    detailName.textContent = brand.name;
    detailSlug.textContent = brand.slug;
    detailImg.hidden = !brand.hasLogo;
    detailImg.src = brand.hasLogo ? brand.detail || brand.image : "";

    const placeholder = detailPreview.querySelector(".no-logo");
    if (placeholder) placeholder.remove();
    if (!brand.hasLogo) {
      const span = document.createElement("span");
      span.className = "muted no-logo";
      span.textContent = "Esta marca no tiene logo";
      detailPreview.appendChild(span);
    }

    detailReplace.textContent = brand.hasLogo ? "Cambiar imagen" : "Agregar imagen";
    detailRemoveLogo.hidden = !brand.hasLogo;

    openModal(detailModal);
  }

  function openCreate() {
    createForm.reset();
    state.pendingFile = null;
    createPreview.hidden = true;
    createPreview.removeAttribute("src");
    createHint.hidden = false;
    openModal(createModal);
    createName.focus();
  }

  // ---------------------------------------------------------------- actions

  async function replaceLogo(slug, file) {
    markBusy(slug, true);
    const body = new FormData();
    body.append("file", file);
    try {
      const updated = await api(`/api/brands/${encodeURIComponent(slug)}/logo`, { method: "POST", body });
      applyBrandUpdate(updated);
      toast(`Logo de ${updated.name} actualizado`, "success");
      if (state.detailSlug === slug) openDetail(slug);
    } catch (error) {
      toast(error.message, "error");
      markBusy(slug, false);
    }
  }

  async function removeLogo(slug) {
    const brand = state.brands.find((item) => item.slug === slug);
    if (!brand) return;
    if (!confirm(`¿Quitar el logo de "${brand.name}"? La marca se mantiene en el listado.`)) return;

    try {
      const updated = await api(`/api/brands/${encodeURIComponent(slug)}/logo`, { method: "DELETE" });
      applyBrandUpdate(updated);
      toast(`Logo de ${updated.name} eliminado`, "success");
      if (state.detailSlug === slug) openDetail(slug);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function deleteBrand(slug) {
    const brand = state.brands.find((item) => item.slug === slug);
    if (!brand) return;
    if (!confirm(`¿Eliminar la marca "${brand.name}" junto con todos sus logos?`)) return;

    try {
      await api(`/api/brands/${encodeURIComponent(slug)}`, { method: "DELETE" });
      state.brands = state.brands.filter((item) => item.slug !== slug);
      renderGrid();
      if (state.detailSlug === slug) {
        state.detailSlug = null;
        closeModal(detailModal);
      }
      toast(`Marca ${brand.name} eliminada`, "success");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  // ---------------------------------------------------------------- events

  function setSize(size) {
    state.size = size;
    document.body.dataset.size = size;
    localStorage.setItem("logoManager.size", size);
    sizeButtons.forEach((button) => button.classList.toggle("active", button.dataset.size === size));
    if (state.brands.length) renderGrid();
  }

  searchInput.addEventListener(
    "input",
    debounce(() => {
      state.query = searchInput.value;
      renderGrid();
    }, 110)
  );

  onlyMissingInput.addEventListener("change", () => {
    state.onlyMissing = onlyMissingInput.checked;
    renderGrid();
  });

  sizeButtons.forEach((button) => button.addEventListener("click", () => setSize(button.dataset.size)));

  $("#new-brand").addEventListener("click", openCreate);

  detailReplace.addEventListener("click", () => detailFile.click());
  detailRemoveLogo.addEventListener("click", () => state.detailSlug && removeLogo(state.detailSlug));
  detailDelete.addEventListener("click", () => state.detailSlug && deleteBrand(state.detailSlug));

  detailFile.addEventListener("change", () => {
    const file = detailFile.files?.[0];
    detailFile.value = "";
    if (file && state.detailSlug) replaceLogo(state.detailSlug, file);
  });

  detailPreview.addEventListener("dragover", (event) => {
    event.preventDefault();
    detailPreview.classList.add("drop-target");
  });
  detailPreview.addEventListener("dragleave", () => detailPreview.classList.remove("drop-target"));
  detailPreview.addEventListener("drop", (event) => {
    event.preventDefault();
    detailPreview.classList.remove("drop-target");
    const file = event.dataTransfer?.files?.[0];
    if (file && state.detailSlug) replaceLogo(state.detailSlug, file);
  });

  // Nueva marca: selección de archivo y drag & drop
  createDrop.addEventListener("click", () => createFile.click());
  createDrop.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      createFile.click();
    }
  });
  createDrop.addEventListener("dragover", (event) => {
    event.preventDefault();
    createDrop.classList.add("drop-target");
  });
  createDrop.addEventListener("dragleave", () => createDrop.classList.remove("drop-target"));
  createDrop.addEventListener("drop", (event) => {
    event.preventDefault();
    createDrop.classList.remove("drop-target");
    const file = event.dataTransfer?.files?.[0];
    if (file) setPendingFile(file);
  });

  createFile.addEventListener("change", () => {
    const file = createFile.files?.[0];
    if (file) setPendingFile(file);
  });

  function setPendingFile(file) {
    state.pendingFile = file;
    createPreview.src = URL.createObjectURL(file);
    createPreview.hidden = false;
    createHint.hidden = true;
  }

  createForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = createName.value.trim();
    if (!name) {
      toast("El nombre de la marca es obligatorio.", "error");
      createName.focus();
      return;
    }

    const body = new FormData();
    body.append("name", name);
    if (state.pendingFile) body.append("file", state.pendingFile);

    createSubmit.disabled = true;
    try {
      const brand = await api("/api/brands", { method: "POST", body });
      applyBrandUpdate(brand);
      closeModal(createModal);
      toast(`Marca ${brand.name} creada`, "success");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      createSubmit.disabled = false;
    }
  });

  document.querySelectorAll("[data-close]").forEach((button) => {
    button.addEventListener("click", () => closeModal(button.closest(".modal")));
  });

  [detailModal, createModal].forEach((modal) => {
    modal.addEventListener("mousedown", (event) => {
      if (event.target === modal) closeModal(modal);
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      [detailModal, createModal].forEach((modal) => {
        if (!modal.hidden) closeModal(modal);
      });
      return;
    }
    const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
    if (event.key === "/" && !typing) {
      event.preventDefault();
      searchInput.focus();
      searchInput.select();
    }
  });

  // Evita que el navegador abra un archivo al soltarlo fuera de una tarjeta
  ["dragover", "drop"].forEach((type) =>
    window.addEventListener(type, (event) => {
      if (!event.target.closest(".card, .dropzone, .detail-preview")) event.preventDefault();
    })
  );

  // ---------------------------------------------------------------- init

  async function loadBrands() {
    const button = $("#refresh");
    button.classList.add("spinning");
    try {
      const data = await api("/api/brands");
      state.brands = data.brands;
      renderGrid();
    } catch (error) {
      summary.textContent = "No se pudo cargar el listado";
      toast(error.message, "error");
    } finally {
      button.classList.remove("spinning");
    }
  }

  $("#refresh").addEventListener("click", loadBrands);

  setSize(state.size);
  loadBrands();
})();
