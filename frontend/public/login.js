// Login gate. The password is sent once over the same origin; the session lives in an HttpOnly cookie.
const form = document.getElementById("login");
const input = document.getElementById("password");
const button = document.getElementById("submit");
const msg = document.getElementById("msg");

function nextPath() {
  const n = new URLSearchParams(location.search).get("next") || "";
  return /^\/(dashboard|today|discover|leads(\/\d+)?|follow-ups|analytics|strategy|settings|import)(\?.*)?$/.test(n) ? n : "/dashboard";
}

function say(text, info = false) {
  msg.textContent = text;
  msg.classList.toggle("info", info);
}

async function checkSetup() {
  try {
    const res = await fetch("/api/setup", { headers: { Accept: "application/json" } });
    const data = await res.json();
    if (!data.configured) {
      say("Not configured yet: " + (data.problems || []).join(" "));
      button.disabled = true;
    }
  } catch (e) {
    say("Can't reach the server.");
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!input.value) {
    say("Enter the password.");
    input.focus();
    return;
  }
  button.disabled = true;
  button.textContent = "Verifying…";
  say("");
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-With": "GodsEye" },
      body: JSON.stringify({ password: input.value }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      input.value = "";
      say("Access granted.", true);
      location.replace(nextPath());
      return;
    }
    say(data.error || "Access denied.");
    form.classList.remove("shake");
    void form.offsetWidth;
    form.classList.add("shake");
    input.select();
  } catch (err) {
    say("Network error. Try again.");
  } finally {
    button.disabled = false;
    button.textContent = "Enter God's Eye";
  }
});

checkSetup();
