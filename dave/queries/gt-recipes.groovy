// @description: Live GregTech recipe lookup: recipes that make (or, with uses=true, consume) an item or fluid, straight from the server's recipe maps, with inputs, outputs, chances, EU/t, tier, duration and special values (cleanroom, coil heat, low gravity, ...). Also vanilla crafting-table recipes for producers.
// @mode: read
// @side: server
// @timeout_ms: 5000
// @param item: string. Item id "modid:name" or "modid:name:meta" (e.g. "gregtech:gt.metaitem.01:32700"), "ore:<oredict name>", or a display-name fragment (slower, exact ids are better)
// @param fluid: string. Fluid registry name instead of an item, e.g. "molten.solderingalloy"
// @param uses: boolean. true: recipes that CONSUME it instead of producing it
// @param map: string. Only recipe maps whose name contains this, e.g. "laserengraver", "assembler"
// @param limit: number. Recipes returned (default 10, max 50)
// @param crafting: boolean. Include crafting-table recipes when looking for producers (default true)
//
// Sources (GT5-Unofficial 5.09.54.265, the GTNH 2.9.0 tag): RecipeMap.ALL_RECIPE_MAPS and getAllRecipes()
// (api/recipe/RecipeMap.java:48,88), RecipeMap.unlocalizedName (:56); GTRecipe public fields mInputs, mOutputs,
// mFluidInputs, mFluidOutputs, mOutputChances, mDuration, mEUt, mSpecialValue, mEnabled, mHidden, mFakeRecipe
// (api/util/GTRecipe.java:67-124) and getMetadataStorage().getEntries() (IRecipeMetadataStorage.java:31), whose
// keys (RecipeMetadataKey, private `identifier`) include CLEANROOM, LOW_GRAVITY, COIL_HEAT (GTRecipeConstants.java).

import net.minecraft.item.crafting.CraftingManager
import net.minecraftforge.fluids.FluidRegistry

def want = params.item ? params.item.toString().trim() : null
def wantFluid = params.fluid ? params.fluid.toString().trim().toLowerCase() : null
boolean uses = params.uses in [true, 'true']
def mapFilter = params.map ? params.map.toString().toLowerCase() : null
int limit = Math.min(50, (params.limit ?: 10) as int)
boolean crafting = !(params.crafting in [false, 'false'])
if (!want && !wantFluid) return [error: 'give item or fluid']

// ---- what are we looking for
def wantItem = null; Integer wantMeta = null; Set wantOre = null; String wantName = null
if (want) {
    if (want.startsWith('ore:')) {
        wantOre = OreDictionary.getOres(want.substring(4)).collect { [it.getItem(), it.getItemDamage()] } as Set
        if (!wantOre) return [error: "no items with ore name ${want.substring(4)}"]
    } else if (want.contains(':')) {
        def parts = want.split(':')
        wantItem = Item.itemRegistry.getObject(parts[0] + ':' + parts[1])
        if (parts.length > 2) wantMeta = parts[2] as int
        if (wantItem == null) return [error: "unknown item id ${parts[0]}:${parts[1]}"]
    } else {
        wantName = want.toLowerCase()
    }
}
def safeName = { s -> try { return s.getDisplayName() } catch (Throwable e) { return null } }
def nameCache = new IdentityHashMap()
def matches = { ItemStack s ->
    if (s == null || s.getItem() == null) return false
    if (wantItem != null) return s.getItem().is(wantItem) && (wantMeta == null || s.getItemDamage() == wantMeta || s.getItemDamage() == 32767)
    if (wantOre != null) return wantOre.any { it[0].is(s.getItem()) && (it[1] == s.getItemDamage() || it[1] == 32767) }
    if (wantName != null) {
        def n = nameCache.get(s)
        if (n == null) { n = (safeName(s) ?: '').toLowerCase(); nameCache.put(s, n) }
        return n.contains(wantName)
    }
    false
}
def matchesFluid = { fs -> fs != null && fs.getFluid() != null && fs.getFluid().getName().toLowerCase() == wantFluid }

def tiers = ['ULV', 'LV', 'MV', 'HV', 'EV', 'IV', 'LuV', 'ZPM', 'UV', 'UHV', 'UEV', 'UIV', 'UMV', 'UXV', 'MAX']
def tierOf = { long eut -> long v = 8; for (t in tiers) { if (eut <= v) return t; v *= 4 }; 'MAX+' }
def stack = { ItemStack s, Integer chance ->
    if (s == null) return null
    def m = [id: dave.markupId(s), count: s.stackSize, name: safeName(s)]
    if (s.getItemDamage() == 32767) m.anyMeta = true
    if (chance != null && chance < 10000) m.chance = (chance / 100.0) + '%'
    m
}
def fluidOf = { fs -> fs == null ? null : dave.fluid(fs) }

def found = []
int total = 0
def maps = dave.cls('gregtech.api.recipe.RecipeMap').ALL_RECIPE_MAPS
for (entry in maps.entrySet()) {
    String mapName = entry.key
    if (mapFilter && !mapName.toLowerCase().contains(mapFilter)) continue
    for (r in entry.value.getAllRecipes()) {
        boolean hit
        if (wantFluid) {
            hit = uses ? (r.mFluidInputs?.any(matchesFluid)) : (r.mFluidOutputs?.any(matchesFluid))
        } else {
            hit = uses ? (r.mInputs?.any(matches)) : (r.mOutputs?.any(matches))
        }
        if (!hit) continue
        total++
        if (found.size() >= limit) continue
        def special = [:]
        try {
            for (e in r.getMetadataStorage().getEntries()) special[dave.get(e.key, 'identifier')] = e.value
        } catch (ignored) { }
        def outs = []
        r.mOutputs?.eachWithIndex { s, i -> if (s != null) outs << stack(s, r.getOutputChance(i)) }
        found << [map: mapName, eut: r.mEUt, tier: tierOf(Math.abs(r.mEUt as long)), ticks: r.mDuration,
                  seconds: r.mDuration / 20.0, specialValue: r.mSpecialValue,
                  inputs: r.mInputs?.findAll { it != null }?.collect { stack(it, null) },
                  fluidInputs: r.mFluidInputs?.findAll { it != null }?.collect(fluidOf),
                  outputs: outs, fluidOutputs: r.mFluidOutputs?.findAll { it != null }?.collect(fluidOf),
                  special: special, enabled: r.mEnabled, hidden: r.mHidden, fake: r.mFakeRecipe]
    }
}

def craftingFound = []
if (crafting && !uses && !wantFluid && !mapFilter) {
    for (rec in CraftingManager.getInstance().getRecipeList()) {
        def out = rec.getRecipeOutput()
        if (!matches(out)) continue
        if (craftingFound.size() >= 5) { craftingFound << '...more'; break }
        def ins = []
        try {
            def raw = null
            try { raw = rec.getInput() } catch (MissingMethodException e) { raw = rec.recipeItems }
            raw?.each { x ->
                if (x instanceof ItemStack) ins << stack(x, null)
                else if (x instanceof List && x) ins << [oneOf: x.take(3).collect { stack(it, null) }]
            }
        } catch (ignored) { ins = null }
        craftingFound << [type: rec.getClass().getSimpleName(), output: stack(out, null), inputs: ins]
    }
}

[query: [item: want, fluid: wantFluid, uses: uses, map: mapFilter], gtRecipesMatched: total, gtRecipesShown: found.size(),
 recipes: found, crafting: craftingFound,
 note: 'eut is per tick at the recipe tier; ticks / 20 = seconds. special holds recipe metadata (cleanroom, coil heat...); specialValue is GT\'s legacy special slot (e.g. EBF heat in some maps).']
