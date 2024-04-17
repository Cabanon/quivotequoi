input = document.getElementById('search')
members = document.querySelectorAll('article');

function filter() {
  query = input.value.toLowerCase();
  tokens = query.split(/\s+/).map((token) => token).filter(Boolean)

  for (const member of members) {
    string = member.textContent.toLowerCase();
    if (tokens.every((token) => string.includes(token))) {
      member.style.display = "";
    } else {
      member.style.display = "none";
    }
  }
}