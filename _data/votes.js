const fs = require('fs');
const initSqlJs = require('sql.js');
const filebuffer = fs.readFileSync('db.sqlite');

function query(db, stmt) {
  res = db.exec(stmt)[0]
  return res.values.map((row) => Object.fromEntries(res.columns.map((colname, index) => ([colname, row[index]]))))
}

function get_positions(db, vote_id) {
  return query(db, `SELECT member_id, position FROM positions JOIN members ON members.id = member_id WHERE vote_id='${vote_id}'`)
}

function get_procedure_title(db, ref) {
  return query(db, `SELECT title FROM procedures WHERE reference='${ref}'`).title
}

function get_votes(db) {
  return query(db, 'SELECT * FROM votes')
}

const arr = initSqlJs().then(function(SQL) {
  const db = new SQL.Database(filebuffer);
  const votes = get_votes(db)
    .map((vote) => ({
      positions: get_positions(db, vote.id),
      procedure_title: get_procedure_title(db, vote.procedure_ref),
      ...vote 
    }))
  return votes
})

module.exports = arr