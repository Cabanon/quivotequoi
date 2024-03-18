async function init() {
	const SQL = await initSqlJs({locateFile: file => `https://sql.js.org/dist/${file}`})

	var dbFileElm = document.getElementById('dbfile');
	var refElm = document.getElementById('ref');
	var titleElm = document.getElementById('title');

	dbFileElm.onchange = () => {
		const f = dbFileElm.files[0];
		const r = new FileReader();
		r.onload = function() {
			const Uints = new Uint8Array(r.result);
			db = new SQL.Database(Uints);
		}
		r.readAsArrayBuffer(f);
	}
}

window.addEventListener("load", init);