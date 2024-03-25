const { parse } = require("csv-parse/sync");
const { diffWords } = require("diff");

const dot = (obj, path) => path.split('.').reduce((a, b) => typeof(a[b]) == 'function' ? a[b].bind(a): a[b], obj);

module.exports = function(eleventyConfig) {
    eleventyConfig.addFilter("date", (dateString) => new Date(dateString).toLocaleDateString('fr-FR', { year: 'numeric', month: 'long', day: 'numeric' }));
    eleventyConfig.addFilter("diff", function(a, b) { return diffWords(a || '', b || '') });

    eleventyConfig.addLiquidFilter("startswith", function(str, value) { return str.startsWith(value) });
    eleventyConfig.addLiquidFilter("find", function(arr, key, value) { return arr.find((obj) => obj[key] == value) });
    eleventyConfig.addLiquidFilter("where", function(arr, key, test, value) {
        return arr.filter((obj) => value ? obj[key][test].bind(obj[key])(value) : obj[key] == test )
    });
    eleventyConfig.addLiquidFilter("where_exp", function(arr, key, cond) {
        return arr.filter((el) => eval(`const { ${key} } = el; ${cond}`))
    });
    eleventyConfig.addLiquidFilter("groupby_exp", function(arr, key, cond) {
        return arr.reduce(
            (groups, obj) => {
                const res = eval(`const { ${key} } = obj; ${cond}`)
                const group = groups.find((g) => g.name == res)
                if (group) group.items.push(obj)
                else groups.push({ name: res, items: [obj] })
                return groups
            },
            []
        )
    });
    eleventyConfig.addLiquidFilter("dot", function(obj, path) { return path.split('.').reduce((a, b) => a[b], obj);});
    eleventyConfig.addLiquidFilter("group_by", function(array, key) {
        return array.reduce(
            (groups, obj) => {
                const group = groups.find((g) => g.name == obj[key])
                if (group) group.items.push(obj)
                else groups.push({ name: obj[key], items: [obj] })
                return groups
            },
            []
        )
    });
    eleventyConfig.addLiquidFilter("where_in", function(arr1, key, arr2) {
        return arr1.filter((e) => arr2.includes(e[key]))
    });

    eleventyConfig.addDataExtension("csv", (contents) => {
        const records = parse(contents, {
            cast: function(value) {
                try {
                    return JSON.parse(value)
                } catch {
                    if (value == 'NULL') return null
                    return value
                }
            },
            columns: true,
            skip_empty_lines: true,
        });
        return records;
    });
};