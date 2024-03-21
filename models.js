const { model, Schema } = require('mongoose');

const memberSchema = Schema({
    id: Number,
    full_name: String,
    party: String,
})

const Member = model('Member', memberSchema);

const positionSchema = Schema({
    position: String,
    mepid: { type: Number, ref: Member },
})
const voteSchema = Schema({
    id: Number,
    title: String,
    reference: String,
    positions: [positionSchema]
})

const Vote = model('Vote', voteSchema);

const procedureSchema = Schema({
    id: Number,
    title: String,
    reference: String,
    positions: [positionSchema]
})

const Procedure = model('Procedure', procedureSchema);
// const Vote = model('Vote', {}, 'votes');
// const startDate = new Date(2019, 7, 2)
// console.log(startDate.toISOString())
// const member_ids = members.map((member) => member.id)
// const votes = await Vote.find({
//     'ts': { $gt: startDate.toISOString() },
//     'votes': { $exists: true },
//     'epref': { $exists: true },
// }).lean()
// const votesExport = votes.map((vote) => ({
//     id: vote.voteid,
//     title: vote.title,
//     reference: Array.isArray(vote.epref) ? vote.epref[0] : vote.epref,
//     positions: Object.entries(vote.votes).flatMap(([position, { groups }]) => Object.values(groups).flat().map(({ mepid }) => ({ position, mepid }))),
// }))
// writeFile('_data/votes.json', "[" + votesExport.map(el => JSON.stringify(el)).join(",") + "]", (err) => console.log(err))

// await disconnect()

module.exports = { Member, Vote }
