"""Generate mac/DiamondMetrics.xcodeproj from scratch — two targets (the
app and its WidgetKit extension), entitlements, and the widget's
Info.plist — so the project never has to be clicked together in Xcode
and can be regenerated any time the file list changes.

    python mac/gen_project.py && xcodebuild -project mac/DiamondMetrics.xcodeproj -target DiamondMetrics build

Signing defaults to "Sign to Run Locally" (ad-hoc), which is all a
personal build needs; set DEVELOPMENT_TEAM below (or in Xcode) to use an
Apple ID personal team instead.
"""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "DiamondMetrics"
PROJ = ROOT / "DiamondMetrics.xcodeproj"
BUNDLE = "com.cromulentlabs.diamondmetrics"
APP_GROUP = "group.com.cromulentlabs.diamondmetrics"
DEPLOY = "14.0"
DEVELOPMENT_TEAM = "9NMHR9YX9B"  # Cole Gardner (Personal Team)


def oid(name: str) -> str:
    """Stable 24-hex object id from a name, so regenerating gives a clean diff."""
    return hashlib.md5(name.encode()).hexdigest()[:24].upper()


shared = ["Shared/Feed.swift", "Shared/LiveScores.swift", "Shared/TeamLogos.swift", "Shared/BasesView.swift"]
app_files = shared + ["App/DiamondMetricsApp.swift"]
widget_files = shared + ["Widgets/DiamondWidgets.swift"]
all_sources = sorted(set(app_files + widget_files))

# --- entitlements + plists ----------------------------------------------------------
# WidgetKit extensions are REQUIRED to be sandboxed (pkd rejects unsandboxed
# plugins outright — confirmed via Console: "plug-ins must be sandboxed").
# App Groups lets the sandboxed app and widget share one container for the
# cached feed/settings (see SharedStore in Feed.swift). Both need a real
# signing team, which is why this only works after Xcode > Settings >
# Accounts has an Apple ID signed in (see DEVELOPMENT_TEAM below).
ENT = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>com.apple.security.app-sandbox</key>
	<true/>
	<key>com.apple.security.network.client</key>
	<true/>
	<key>com.apple.security.application-groups</key>
	<array>
		<string>{APP_GROUP}</string>
	</array>
</dict>
</plist>
"""
(SRC / "App" / "DiamondMetrics.entitlements").write_text(ENT)
(SRC / "Widgets" / "DiamondWidgets.entitlements").write_text(ENT)
(SRC / "Widgets" / "Info.plist").write_text("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>NSExtension</key>
	<dict>
		<key>NSExtensionPointIdentifier</key>
		<string>com.apple.widgetkit-extension</string>
	</dict>
</dict>
</plist>
""")

# --- pbxproj ---------------------------------------------------------------------------
objs = []  # (id, body)


def add(name, body):
    i = oid(name)
    objs.append((i, body))
    return i


file_refs, build_files = {}, {}
for f in all_sources:
    file_refs[f] = add(f"ref:{f}", f'{{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = "{f}"; sourceTree = "<group>"; }}')
for f, tgt in [(f, "app") for f in app_files] + [(f, "widget") for f in widget_files]:
    build_files[(f, tgt)] = add(f"build:{tgt}:{f}", f"{{isa = PBXBuildFile; fileRef = {file_refs[f]}; }}")
for extra in ["App/DiamondMetrics.entitlements", "Widgets/DiamondWidgets.entitlements", "Widgets/Info.plist"]:
    file_refs[extra] = add(f"ref:{extra}", f'{{isa = PBXFileReference; lastKnownFileType = text.plist.xml; path = "{extra}"; sourceTree = "<group>"; }}')

app_product = add("product:app", '{isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = "Diamond Metrics.app"; sourceTree = BUILT_PRODUCTS_DIR; }')
widget_product = add("product:widget", '{isa = PBXFileReference; explicitFileType = "wrapper.app-extension"; includeInIndex = 0; path = DiamondWidgets.appex; sourceTree = BUILT_PRODUCTS_DIR; }')
widget_embed = add("build:embed:widget", f"{{isa = PBXBuildFile; fileRef = {widget_product}; settings = {{ATTRIBUTES = (RemoveHeadersOnCopy, ); }}; }}")

src_group = add("group:src", "{isa = PBXGroup; children = (" + ", ".join(file_refs[f] for f in list(all_sources) + ["App/DiamondMetrics.entitlements", "Widgets/DiamondWidgets.entitlements", "Widgets/Info.plist"]) + ", ); path = DiamondMetrics; sourceTree = \"<group>\"; }")
products_group = add("group:products", f"{{isa = PBXGroup; children = ({app_product}, {widget_product}, ); name = Products; sourceTree = \"<group>\"; }}")
main_group = add("group:main", f"{{isa = PBXGroup; children = ({src_group}, {products_group}, ); sourceTree = \"<group>\"; }}")

app_sources = add("phase:app:sources", "{isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = (" + ", ".join(build_files[(f, 'app')] for f in app_files) + ", ); runOnlyForDeploymentPostprocessing = 0; }")
widget_sources = add("phase:widget:sources", "{isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = (" + ", ".join(build_files[(f, 'widget')] for f in widget_files) + ", ); runOnlyForDeploymentPostprocessing = 0; }")
app_frameworks = add("phase:app:frameworks", "{isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }")
widget_frameworks = add("phase:widget:frameworks", "{isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }")
app_resources = add("phase:app:resources", "{isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }")
widget_resources = add("phase:widget:resources", "{isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }")
embed_phase = add("phase:app:embed", f'{{isa = PBXCopyFilesBuildPhase; buildActionMask = 2147483647; dstPath = ""; dstSubfolderSpec = 13; files = ({widget_embed}, ); name = "Embed Foundation Extensions"; runOnlyForDeploymentPostprocessing = 0; }}')

team = (
    f'DEVELOPMENT_TEAM = {DEVELOPMENT_TEAM}; CODE_SIGN_STYLE = Automatic; CODE_SIGN_IDENTITY = "Apple Development";'
    if DEVELOPMENT_TEAM else
    # WidgetKit extensions refuse to register with the widget gallery
    # under a plain ad-hoc signature (spctl rejects it) — Automatic
    # signing with no explicit team lets xcodebuild -allowProvisioningUpdates
    # pick the sole personal team on the signed-in Apple ID.
    'CODE_SIGN_STYLE = Automatic; CODE_SIGN_IDENTITY = "Apple Development";'
)
common = f"""
    ALWAYS_SEARCH_USER_PATHS = NO; CLANG_ENABLE_MODULES = YES; ENABLE_HARDENED_RUNTIME = YES;
    MACOSX_DEPLOYMENT_TARGET = {DEPLOY}; SDKROOT = macosx; SWIFT_VERSION = 5.0; SWIFT_EMIT_LOC_STRINGS = YES;
    {team} ENABLE_USER_SCRIPT_SANDBOXING = YES; CURRENT_PROJECT_VERSION = 1; MARKETING_VERSION = 1.0;
    ASSETCATALOG_COMPILER_GLOBAL_ACCENT_COLOR_NAME = AccentColor;"""
app_settings = f"""{common}
    PRODUCT_BUNDLE_IDENTIFIER = {BUNDLE}; PRODUCT_NAME = "Diamond Metrics"; GENERATE_INFOPLIST_FILE = YES;
    INFOPLIST_KEY_LSApplicationCategoryType = "public.app-category.sports"; INFOPLIST_KEY_NSHumanReadableCopyright = "";
    CODE_SIGN_ENTITLEMENTS = DiamondMetrics/App/DiamondMetrics.entitlements; COMBINE_HIDPI_IMAGES = YES;
    LD_RUNPATH_SEARCH_PATHS = ("$(inherited)", "@executable_path/../Frameworks");"""
widget_settings = f"""{common}
    PRODUCT_BUNDLE_IDENTIFIER = {BUNDLE}.widgets; PRODUCT_NAME = DiamondWidgets; INFOPLIST_FILE = DiamondMetrics/Widgets/Info.plist;
    GENERATE_INFOPLIST_FILE = YES; INFOPLIST_KEY_CFBundleDisplayName = "Diamond Metrics";
    INFOPLIST_KEY_NSHumanReadableCopyright = ""; SKIP_INSTALL = YES;
    CODE_SIGN_ENTITLEMENTS = DiamondMetrics/Widgets/DiamondWidgets.entitlements;
    LD_RUNPATH_SEARCH_PATHS = ("$(inherited)", "@executable_path/../Frameworks", "@executable_path/../../../../Frameworks");"""


def configs(prefix, settings):
    debug = add(f"cfg:{prefix}:debug", f'{{isa = XCBuildConfiguration; buildSettings = {{{settings} DEBUG_INFORMATION_FORMAT = dwarf; ONLY_ACTIVE_ARCH = YES; SWIFT_OPTIMIZATION_LEVEL = "-Onone"; SWIFT_ACTIVE_COMPILATION_CONDITIONS = DEBUG; GCC_OPTIMIZATION_LEVEL = 0; }}; name = Debug; }}')
    release = add(f"cfg:{prefix}:release", f'{{isa = XCBuildConfiguration; buildSettings = {{{settings} DEBUG_INFORMATION_FORMAT = "dwarf-with-dsym"; SWIFT_OPTIMIZATION_LEVEL = "-O"; SWIFT_COMPILATION_MODE = wholemodule; }}; name = Release; }}')
    return add(f"cfglist:{prefix}", f"{{isa = XCConfigurationList; buildConfigurations = ({debug}, {release}, ); defaultConfigurationIsVisible = 0; defaultConfigurationName = Release; }}")


project_cfg = configs("project", "")
app_cfg = configs("app", app_settings)
widget_cfg = configs("widget", widget_settings)

widget_target = add("target:widget", f'{{isa = PBXNativeTarget; buildConfigurationList = {widget_cfg}; buildPhases = ({widget_sources}, {widget_frameworks}, {widget_resources}, ); buildRules = (); dependencies = (); name = DiamondWidgets; productName = DiamondWidgets; productReference = {widget_product}; productType = "com.apple.product-type.app-extension"; }}')
project_id = oid("project")
proxy = add("proxy:widget", f'{{isa = PBXContainerItemProxy; containerPortal = {project_id}; proxyType = 1; remoteGlobalIDString = {widget_target}; remoteInfo = DiamondWidgets; }}')
dep = add("dep:widget", f"{{isa = PBXTargetDependency; target = {widget_target}; targetProxy = {proxy}; }}")
app_target = add("target:app", f'{{isa = PBXNativeTarget; buildConfigurationList = {app_cfg}; buildPhases = ({app_sources}, {app_frameworks}, {app_resources}, {embed_phase}, ); buildRules = (); dependencies = ({dep}, ); name = DiamondMetrics; productName = DiamondMetrics; productReference = {app_product}; productType = "com.apple.product-type.application"; }}')
objs.append((project_id, f'{{isa = PBXProject; attributes = {{BuildIndependentTargetsInParallel = 1; LastSwiftUpdateCheck = 1640; LastUpgradeCheck = 1640; TargetAttributes = {{{app_target} = {{CreatedOnToolsVersion = 16.4; }}; {widget_target} = {{CreatedOnToolsVersion = 16.4; }}; }}; }}; buildConfigurationList = {project_cfg}; compatibilityVersion = "Xcode 15.0"; developmentRegion = en; hasScannedForEncodings = 0; knownRegions = (en, Base, ); mainGroup = {main_group}; productRefGroup = {products_group}; projectDirPath = ""; projectRoot = ""; targets = ({app_target}, {widget_target}, ); }}'))

body = "\n".join(f"\t\t{i} = {b};" for i, b in objs)
PROJ.mkdir(exist_ok=True)
(PROJ / "project.pbxproj").write_text(f"""// !$*UTF8*$!
{{
	archiveVersion = 1;
	classes = {{
	}};
	objectVersion = 60;
	objects = {{
{body}
	}};
	rootObject = {project_id};
}}
""")

# --- schemes ---------------------------------------------------------------------
# Written explicitly (not left to Xcode's autocreation) so "DiamondMetrics" is
# always a selectable, runnable scheme — autocreation has repeatedly only
# picked up the widget target across regenerations, leaving no way to Run
# the app from Xcode's toolbar.
CONTAINER = f"container:{PROJ.name}"


def buildable_ref(target_id, name, product):
    return (f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{target_id}" '
            f'BuildableName="{product}" BlueprintName="{name}" ReferencedContainer="{CONTAINER}">\n      </BuildableReference>')


app_ref = buildable_ref(app_target, "DiamondMetrics", "Diamond Metrics.app")
widget_ref = buildable_ref(widget_target, "DiamondWidgets", "DiamondWidgets.appex")

app_scheme = f"""<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="1640" version="1.7">
   <BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES">
      <BuildActionEntries>
         <BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">
            {app_ref}
         </BuildActionEntry>
      </BuildActionEntries>
   </BuildAction>
   <LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.DebuggerFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" debugServiceExtension="internal" allowLocationSimulation="YES">
      <BuildableProductRunnable runnableDebuggingMode="0">
         {app_ref}
      </BuildableProductRunnable>
   </LaunchAction>
   <ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="YES" savedToolIdentifier="" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES">
      <BuildableProductRunnable runnableDebuggingMode="0">
         {app_ref}
      </BuildableProductRunnable>
   </ProfileAction>
   <AnalyzeAction buildConfiguration="Debug"/>
   <ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>
"""

widget_scheme = f"""<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="1640" version="1.7">
   <BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES">
      <BuildActionEntries>
         <BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">
            {widget_ref}
         </BuildActionEntry>
      </BuildActionEntries>
   </BuildAction>
   <LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.DebuggerFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" debugServiceExtension="internal" askForAppToLaunch="YES" launchAutomaticallySubstyle="2">
      <MacroExpansion>
         {widget_ref}
      </MacroExpansion>
   </LaunchAction>
   <ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="YES" savedToolIdentifier="" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES">
      <MacroExpansion>
         {widget_ref}
      </MacroExpansion>
   </ProfileAction>
   <AnalyzeAction buildConfiguration="Debug"/>
   <ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>
"""

schemes_dir = PROJ / "xcshareddata" / "xcschemes"
schemes_dir.mkdir(parents=True, exist_ok=True)
(schemes_dir / "DiamondMetrics.xcscheme").write_text(app_scheme)
(schemes_dir / "DiamondWidgets.xcscheme").write_text(widget_scheme)

# Mark both shared and DiamondMetrics as the default/last-used scheme, so
# Xcode's toolbar picks it automatically on open instead of whichever
# scheme alphabetically or historically came first.
management = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>SchemeUserState</key>
	<dict>
		<key>DiamondMetrics.xcscheme_^#shared#^_</key>
		<dict>
			<key>orderHint</key>
			<integer>0</integer>
		</dict>
		<key>DiamondWidgets.xcscheme_^#shared#^_</key>
		<dict>
			<key>orderHint</key>
			<integer>1</integer>
		</dict>
	</dict>
	<key>SuppressBuildableAutocreation</key>
	<dict/>
</dict>
</plist>
"""
user_schemes_dir = PROJ / "xcuserdata" / f"{Path.home().name}.xcuserdatad" / "xcschemes"
user_schemes_dir.mkdir(parents=True, exist_ok=True)
(user_schemes_dir / "xcschememanagement.plist").write_text(management)

print(f"wrote {PROJ}")
