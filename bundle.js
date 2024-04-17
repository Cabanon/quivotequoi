input = document.getElementById('search')
theme = document.getElementById('theme');
area = document.getElementById('area');
lis = document.getElementById("list").getElementsByTagName('article');

getSelectedValue = (select) => select.selectedIndex > 0 ? select.options[select.selectedIndex].text : '' 

function filter() {
  query = input.value.toLowerCase();
  tokens = query.split(/\s+/).map((token) => token).filter(Boolean)

  for (const li of lis) {
    string = li.getElementsByTagName("a")[0].textContent.toLowerCase();
    header = li.getElementsByTagName("header")[0].textContent;
    if (header.includes(getSelectedValue(theme))
      && header.includes(getSelectedValue(area))
      && (tokens.length == 0 || tokens.every((token) => string.includes(token)))
    ) {
      li.style.display = "";
    } else {
      li.style.display = "none";
    }
  }
}