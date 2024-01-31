from tests.fixtures import api, PROJECT_NAME

assert api

def test_kitsu_addon(api):
    
    # /api/addons
    res = api.get("addons")
    assert res.data.get("addons"), "No addons found"

    # map addons list into a dict
    addons = {addon["name"]: addon for addon in res.data["addons"]}

    addon = addons.get("kitsu")   
    assert addon, "Kitsu addon not found"

    # get the current version of the addon
    version = addon['productionVersion']


    print(version)

    # /api/addons/kitsu/1.0.0/pairing
    res = api.get(f'addons/kitsu/{version}/pairing')

    print(res.data)





    # addons = res.data['addons']



    
    # print(res.data)
    assert False