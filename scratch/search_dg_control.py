with open("scratch/bing_first_50k.html", "r", encoding="utf-8") as f:
    text = f.read()

# Let's count how many times some common Bing image structures appear
print("dgControl count:", text.count("dgControl"))
print("iusc count:", text.count("iusc"))
print("dg_u count:", text.count("dg_u"))
print("imgpt count:", text.count("imgpt"))
print("murl count:", text.count("murl"))
print("turl count:", text.count("turl"))
print("OIP count:", text.count("OIP"))
print("ts1.mm.bing.net count:", text.count("ts1.mm.bing.net"))
print("th?id= count:", text.count("th?id="))
