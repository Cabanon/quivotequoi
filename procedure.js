input = document.getElementById('member')
articles = document.querySelectorAll('section.tabs article');

function filter(value) {
  for (const article of articles) {
    text = article.querySelector('div.hidden')?.textContent;
    if (text && value.split(',').some((val) => text.includes(val))) {
      article.style.display = "";
    } else {
      article.style.display = "none";
    }
  }
}