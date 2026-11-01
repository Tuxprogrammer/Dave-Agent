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

def want = params.item ? params.item.toString().trim() : null
def wantFluid = params.fluid ? params.fluid.toString().trim().toLowerCase() : null
boolean uses = params.uses in [true, 'true']
def mapFilter = params.map ? params.map.toString().toLowerCase() : null
int limit = Math.min(50, (params.limit ?: 10) as int)
boolean crafting = !(params.crafting in [false, 'false'])
if (!want && !wantFluid) return [error: 'give item or fluid']

// The scan over every recipe map runs in Java (dave.gtRecipes): GTNH has well over 100,000 recipes.
def scan = dave.gtRecipes(wantFluid ? null : want, wantFluid, uses, mapFilter, limit)
if (scan.error) return [error: scan.error]

def safeName = { s -> try { return s.getDisplayName() } catch (Throwable e) { return null } }
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

def found = scan.recipes.collect { row ->
    def r = row.recipe
    def special = [:]
    try {
        for (e in r.getMetadataStorage().getEntries()) special[dave.get(e.key, 'identifier')] = e.value
    } catch (Throwable ignored) { }
    def outs = []
    r.mOutputs?.eachWithIndex { s, i -> if (s != null) outs << stack(s, r.getOutputChance(i)) }
    [map: row.map, eut: r.mEUt, tier: tierOf(Math.abs(r.mEUt as long)), ticks: r.mDuration,
     seconds: r.mDuration / 20.0, specialValue: r.mSpecialValue,
     inputs: r.mInputs?.findAll { it != null }?.collect { stack(it, null) },
     fluidInputs: r.mFluidInputs?.findAll { it != null }?.collect(fluidOf),
     outputs: outs, fluidOutputs: r.mFluidOutputs?.findAll { it != null }?.collect(fluidOf),
     special: special, enabled: r.mEnabled, hidden: r.mHidden, fake: r.mFakeRecipe]
}

def craftingFound = []
if (crafting && !uses && !wantFluid && !mapFilter) {
    def matcher = dave.items(want)
    for (rec in CraftingManager.getInstance().getRecipeList()) {
        def out = rec.getRecipeOutput()
        if (!matcher.test(out)) continue
        if (craftingFound.size() >= 5) { craftingFound << '...more'; break }
        def ins = []
        try {
            def raw = null
            try { raw = rec.getInput() } catch (MissingMethodException e) { raw = rec.recipeItems }
            raw?.each { x ->
                if (x instanceof ItemStack) ins << stack(x, null)
                else if (x instanceof List && x) ins << [oneOf: x.take(3).collect { stack(it, null) }]
            }
        } catch (Throwable ignored) { ins = null }
        craftingFound << [type: rec.getClass().getSimpleName(), output: stack(out, null), inputs: ins]
    }
}

[query: [item: want, fluid: wantFluid, uses: uses, map: mapFilter], gtRecipesMatched: scan.matched,
 gtRecipesShown: found.size(), recipes: found, crafting: craftingFound,
 note: 'eut is per tick at the recipe tier; ticks / 20 = seconds. An input with count 0 is not consumed (lens, mold, programmed circuit). special holds recipe metadata (cleanroom, coil heat...); specialValue is GT\'s legacy special slot (e.g. EBF heat in some maps).']
