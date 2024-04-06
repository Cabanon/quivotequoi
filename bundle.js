input = document.getElementById('search')
select = document.getElementById('theme');
lis = document.getElementById("list").getElementsByTagName('article');

function filter() {
  query = input.value.toLowerCase();
  tokens = query.split(/\s+/).map((token) => token).filter(Boolean)
  idx = select.selectedIndex
  theme = idx > 0 ? select.options[idx].text : '' 

  for (const li of lis) {
    string = li.getElementsByTagName("a")[0].innerText.toLowerCase();
    header = li.getElementsByTagName("header")[0].innerText;
    if ((tokens.length == 0 || tokens.every((token) => string.includes(token)))
      && header.includes(theme)
    ) {
      li.style.display = "";
    } else {
      li.style.display = "none";
    }
  }
}