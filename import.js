const { JSDOM } = require("jsdom");

async function subjects() {
    await fetch("https://oeil.secure.europarl.europa.eu/oeil/search/search.do?searchTab=y", {
        "credentials": "same-origin",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "fr,fr-FR;q=0.8,en-US;q=0.5,en;q=0.3",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache"
        },
        "referrer": "https://oeil.secure.europarl.europa.eu/oeil/info/info2.do",
        "method": "GET",
        "mode": "cors"
    });
    const response = await fetch("https://oeil.secure.europarl.europa.eu/oeil/search/facet.do?facet=internetSubject_s&snippet=true&sort=d&rows=10&searchTab=y&_=1711230122958", {
        "credentials": "same-origin",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
            "Accept": "*/*",
            "Accept-Language": "fr,fr-FR;q=0.8,en-US;q=0.5,en;q=0.3",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache"
        },
        "referrer": "https://oeil.secure.europarl.europa.eu/oeil/search/search.do?searchTab=y",
        "method": "GET",
        "mode": "cors"
    });
    return response.text()
    const dom = new JSDOM(response.text())
    return dom.window.document.getElementById('tree')
}